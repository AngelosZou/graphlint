# -*- coding: utf-8 -*-
"""Database and IndexLock tests."""

import os
import sqlite3
import tempfile

import pytest

from graphlint.analyzer._types import (
    EdgeInfo,
    GraphBuildResult,
    NodeInfo,
    ParseResult,
)
from graphlint.analyzer.language.c.imports import CIncludeInfo
from graphlint.incremental._db_ops import update_db
from graphlint.incremental.indexer import IncrementalIndexer
from graphlint.storage.db import Database, IndexLock


@pytest.mark.timeout(30)
class TestIndexLock:
    """IndexLock concurrent write lock tests."""

    def test_index_lock(self):
        """Lock creates .lock file, release removes it."""
        with tempfile.TemporaryDirectory() as tmpdir:
            lock = IndexLock(tmpdir)
            lock_path = lock.lock_path

            with lock:
                # Lock file should exist
                assert os.path.isfile(lock_path), ".lock file should exist"
                # Verify lock file is openable
                with open(lock_path, "r"):
                    pass

            # After release, lock file may still exist (unlocked file, not deleted)
            # But file can be opened by other processes
            assert lock._fd is None


@pytest.mark.timeout(30)
class TestDatabaseSchemaReconciliation:
    """Stored schema incompatible with code → drop + recreate on open."""

    def test_fresh_db_stamps_schema_version(self, tmp_path):
        """A brand-new Database must carry the current schema version."""
        from graphlint.storage.schema import SCHEMA_VERSION, get_user_version

        db = Database(str(tmp_path))
        try:
            assert db.schema_reset is False
            assert get_user_version(db.conn) == SCHEMA_VERSION
        finally:
            db.close()

    def test_compatible_db_is_preserved(self, tmp_path):
        """A matching-version database is reused as-is (no reset)."""
        db = Database(str(tmp_path))
        db.execute(
            "INSERT INTO files (path, hash, size_bytes, mtime_ns) "
            "VALUES ('a.py', 'h', 1, 1)"
        )
        db.close()

        db2 = Database(str(tmp_path))
        try:
            assert db2.schema_reset is False
            row = db2.fetchone("SELECT path FROM files")
            assert row is not None and row["path"] == "a.py"
        finally:
            db2.close()

    def test_unversioned_db_is_reset(self, tmp_path, capsys):
        """A pre-versioning DB (user_version=0, missing new columns)
        is dropped."""
        from graphlint.storage.schema import SCHEMA_VERSION, get_user_version

        db = Database(str(tmp_path))
        db.execute(
            "INSERT INTO files (path, hash, size_bytes, mtime_ns) "
            "VALUES ('a.py', 'h', 1, 1)"
        )
        # Simulate a database written by an older graphlint: unversioned and
        # lacking the columns the current INSERT statements rely on.
        db.execute("ALTER TABLE nodes DROP COLUMN is_partial")
        db.execute("ALTER TABLE nodes DROP COLUMN canonical_name")
        db.execute("ALTER TABLE nodes DROP COLUMN visibility")
        db.execute("PRAGMA user_version = 0")
        db.close()

        db2 = Database(str(tmp_path))
        try:
            assert db2.schema_reset is True
            # Old data gone, fresh schema restored
            assert db2.fetchone("SELECT COUNT(*) AS c FROM files")["c"] == 0
            cols = [r[1] for r in db2.execute("PRAGMA table_info(nodes)")]
            assert "is_partial" in cols
            assert get_user_version(db2.conn) == SCHEMA_VERSION
            err = capsys.readouterr().err
            assert "schema mismatch" in err
        finally:
            db2.close()

    def test_newer_version_db_is_reset(self, tmp_path):
        """A DB written by a newer graphlint (future schema) is dropped too."""
        from graphlint.storage.schema import SCHEMA_VERSION, get_user_version

        db = Database(str(tmp_path))
        db.execute("PRAGMA user_version = 999")
        db.close()

        db2 = Database(str(tmp_path))
        try:
            assert db2.schema_reset is True
            assert get_user_version(db2.conn) == SCHEMA_VERSION
        finally:
            db2.close()


@pytest.mark.timeout(30)
class TestDatabase:
    """Database class tests."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Use temp dir as root_dir, let Database create .graphlint/db.sqlite."""
        with tempfile.TemporaryDirectory() as tmpdir:
            self.tmpdir = tmpdir
            # Database init creates .graphlint/db.sqlite and tables
            self.db = Database(tmpdir)
            yield
            if self.db.conn:
                self.db.close()

    def test_db_connect(self):
        """Verify connection object."""
        assert self.db.conn is not None
        assert isinstance(self.db.conn, sqlite3.Connection)
        # Verify db_path points to an existing file
        assert os.path.isfile(self.db.db_path)

    def test_execute_fetchone(self):
        """INSERT then fetchone SELECT, verify Row object behavior."""
        self.db.execute(
            "INSERT INTO files (path, hash, size_bytes, mtime_ns) VALUES (?, ?, ?, ?)",
            ("/test.py", "abc", 100, 12345),
        )

        row = self.db.fetchone(
            "SELECT path, hash, size_bytes FROM files WHERE id=?", (1,)
        )
        assert row is not None, "Should return a row"
        # Verify Row is accessible by key
        assert row["path"] == "/test.py"
        assert row["hash"] == "abc"
        assert row["size_bytes"] == 100
        # Verify Row is accessible by index
        assert row[0] == "/test.py"

    def test_execute_fetchone_no_result(self):
        """Query with no results returns None."""
        row = self.db.fetchone("SELECT * FROM files WHERE id=?", (999,))
        assert row is None

    def test_executemany(self):
        """Batch insert multiple records, fetchall verifies count."""
        params = [(f"/test{i}.py", f"hash{i}", 100 + i, 10000 + i) for i in range(5)]
        self.db.executemany(
            "INSERT INTO files (path, hash, size_bytes, mtime_ns) VALUES (?, ?, ?, ?)",
            params,
        )

        rows = self.db.fetchall("SELECT * FROM files ORDER BY id")
        assert len(rows) == 5

    def test_transaction_context(self):
        """Commit data within transaction context, verify persistence."""
        with self.db.transaction():
            self.db.execute(
                "INSERT INTO files (path, hash, size_bytes, mtime_ns) VALUES (?, ?, ?, ?)",
                ("/tx_test.py", "txhash", 200, 99999),
            )

        # After commit, data should be queryable
        row = self.db.fetchone("SELECT path FROM files WHERE id=?", (1,))
        assert row is not None
        assert row["path"] == "/tx_test.py"

    def test_transaction_rollback(self):
        """Invalid SQL in transaction, verify no partial write."""
        # Insert a valid record first
        self.db.execute(
            "INSERT INTO files (path, hash, size_bytes, mtime_ns) VALUES (?, ?, ?, ?)",
            ("/before_tx.py", "bef", 100, 1),
        )

        # Start transaction and execute invalid SQL
        try:
            with self.db.transaction():
                self.db.execute(
                    "INSERT INTO files (path, hash, size_bytes, mtime_ns) VALUES (?, ?, ?, ?)",
                    ("/good.py", "good", 200, 2),
                )
                # Invalid SQL (table doesn't exist)
                self.db.execute("INSERT INTO nonexistent (id) VALUES (?)", (1,))
        except Exception:
            pass

        # Verify valid record inserted in transaction was rolled back
        rows = self.db.fetchall("SELECT * FROM files")
        assert len(rows) == 1  # Only /before_tx.py

    def test_close(self):
        """Cannot query after closing connection."""
        self.db.close()
        with pytest.raises(sqlite3.ProgrammingError):
            self.db.execute("SELECT 1")

    def test_executemany_zero(self):
        """Executing with empty param list should not error."""
        self.db.executemany(
            "INSERT INTO files (path, hash, size_bytes, mtime_ns) VALUES (?, ?, ?, ?)",
            [],
        )
        rows = self.db.fetchall("SELECT * FROM files")
        assert len(rows) == 0

    def test_begin_commit(self):
        """Manual begin_transaction and commit should work."""
        self.db.begin_transaction()
        self.db.execute(
            "INSERT INTO files (path, hash, size_bytes, mtime_ns) VALUES (?, ?, ?, ?)",
            ("/manual.py", "mhash", 300, 555),
        )
        self.db.commit()

        row = self.db.fetchone("SELECT path FROM files WHERE id=?", (1,))
        assert row["path"] == "/manual.py"

    def test_rollback(self):
        """Manual transaction rollback."""
        self.db.begin_transaction()
        self.db.execute(
            "INSERT INTO files (path, hash, size_bytes, mtime_ns) VALUES (?, ?, ?, ?)",
            ("/rollback.py", "rhash", 400, 777),
        )
        self.db.rollback()

        rows = self.db.fetchall("SELECT * FROM files")
        assert len(rows) == 0


class TestCIncludePersistence:
    """C ``#include`` records survive the DB round trip (incremental builds)."""

    @staticmethod
    def _br_with_includes(files: dict[str, list[CIncludeInfo]]) -> GraphBuildResult:
        prs = {
            fp: ParseResult(file_path=fp, imports=imps)
            for fp, imps in files.items()
        }
        return GraphBuildResult(files=list(files), files_data=prs)

    def test_update_db_persists_c_includes(self, tmp_path):
        db = Database(str(tmp_path))
        br = self._br_with_includes({
            "src/main.c": [
                CIncludeInfo(include_path="helper.h", line=2),
                CIncludeInfo(include_path="math/vec.h", line=3),
            ],
        })
        update_db(db, br, [], ["src/main.c"], str(tmp_path), {})
        rows = db.fetchall(
            "SELECT file_id, import_line, module_path, import_type, is_used "
            "FROM imports ORDER BY import_line"
        )
        assert len(rows) == 2
        assert rows[0]["module_path"] == "helper.h"
        assert rows[0]["import_line"] == 2
        assert rows[0]["import_type"] == "c_include"
        assert rows[1]["module_path"] == "math/vec.h"

    def test_load_unchanged_restores_c_includes(self, tmp_path):
        db = Database(str(tmp_path))
        br = self._br_with_includes({
            "src/main.c": [CIncludeInfo(include_path="helper.h", line=2)],
        })
        update_db(db, br, [], ["src/main.c"], str(tmp_path), {})
        indexer = IncrementalIndexer(str(tmp_path), db)
        restored = indexer._load_unchanged({"src/main.c"})
        assert "src/main.c" in restored
        imps = restored["src/main.c"].imports
        assert len(imps) == 1
        assert imps[0].include_path == "helper.h"
        assert imps[0].line == 2

    def test_system_and_unresolvable_includes_not_persisted(self, tmp_path):
        db = Database(str(tmp_path))
        # System includes never reach ParseResult.imports; nothing with an
        # empty include_path should be stored either.
        br = self._br_with_includes({
            "src/main.c": [CIncludeInfo(include_path="", line=0)],
        })
        update_db(db, br, [], ["src/main.c"], str(tmp_path), {})
        rows = db.fetchall("SELECT * FROM imports")
        assert rows == []

    def test_module_level_use_refs_round_trip(self, tmp_path):
        """Genuine 0→target uses survive the DB round trip as module_ref rows."""
        db = Database(str(tmp_path))
        node = NodeInfo(
            id=7, file_id=1, name="HELPER_H",
            qualified_name="src.helper.HELPER_H", node_type="macro",
        )
        edge = EdgeInfo(
            source_id=0, target_id=7, edge_type="read", file_id=1, line=2,
        )
        br = GraphBuildResult(
            files=["src/helper.h"],
            files_data={"src/helper.h": ParseResult(file_path="src/helper.h")},
            nodes=[node],
            edges=[edge],
            node_id_map={7: node},
        )
        update_db(db, br, [], ["src/helper.h"], str(tmp_path), {})
        rows = db.fetchall(
            "SELECT import_line, module_path, import_type FROM imports"
        )
        assert len(rows) == 1
        assert rows[0]["module_path"] == "src.helper.HELPER_H"
        assert rows[0]["import_type"] == "module_ref:read"
        assert rows[0]["import_line"] == 2

        indexer = IncrementalIndexer(str(tmp_path), db)
        restored = indexer._load_unchanged({"src/helper.h"})
        refs = restored["src/helper.h"].references
        assert len(refs) == 1
        assert refs[0].target_name == "src.helper.HELPER_H"
        assert refs[0].edge_type == "read"
        assert refs[0].line == 2

    def test_synthetic_module_edges_not_persisted(self, tmp_path):
        """Synthetic module edges (line = 0) are rebuilt each build, not stored."""
        db = Database(str(tmp_path))
        node = NodeInfo(
            id=7, file_id=1, name="gv",
            qualified_name="src.main.gv", node_type="variable",
        )
        edge = EdgeInfo(
            source_id=0, target_id=7, edge_type="read", file_id=1, line=0,
        )
        br = GraphBuildResult(
            files=["src/main.c"],
            files_data={"src/main.c": ParseResult(file_path="src/main.c")},
            nodes=[node],
            edges=[edge],
            node_id_map={7: node},
        )
        update_db(db, br, [], ["src/main.c"], str(tmp_path), {})
        rows = db.fetchall("SELECT * FROM imports")
        assert rows == []
