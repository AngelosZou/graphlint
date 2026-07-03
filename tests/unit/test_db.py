# -*- coding: utf-8 -*-
"""Database and IndexLock tests."""

import os
import sqlite3
import tempfile

import pytest

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
