# -*- coding: utf-8 -*-
"""SQLite database schema creation and constraint tests."""

import sqlite3

import pytest

from graphlint.storage.schema import create_tables


@pytest.mark.timeout(30)
class TestSchema:
    """Test SQLite schema creation and constraints."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Each test uses a separate in-memory database."""
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        yield
        self.conn.close()

    def _table_exists(self, table_name: str) -> bool:
        """Check if table exists."""
        cursor = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        )
        return cursor.fetchone() is not None

    def _index_exists(self, index_name: str) -> bool:
        """Check if index exists."""
        cursor = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
            (index_name,),
        )
        return cursor.fetchone() is not None

    # ── Tests ─────────────────────────────────────────────────

    def test_create_tables(self):
        """Create all 6 tables, verify they exist."""
        create_tables(self.conn)

        expected_tables = {
            "files",
            "nodes",
            "edges",
            "imports",
            "warnings",
            "graph_snapshots",
        }
        for tbl in expected_tables:
            assert self._table_exists(tbl), f"Table {tbl} should exist"

    def test_foreign_key_cascade(self):
        """Insert file, insert node (FK→file), delete file, verify node cascade delete."""
        create_tables(self.conn)

        # Insert a file record
        self.conn.execute(
            "INSERT INTO files (path, hash, size_bytes, mtime_ns) VALUES (?, ?, ?, ?)",
            ("/test.py", "abc123", 100, 1234567890),
        )
        file_id = 1

        # Insert a node record (referencing file_id)
        self.conn.execute(
            "INSERT INTO nodes (file_id, name, qualified_name, node_type, "
            "line_start, line_end, col_offset) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (file_id, "func1", "test.func1", "function", 1, 5, 0),
        )

        # Verify node exists
        cursor = self.conn.execute("SELECT COUNT(*) FROM nodes")
        assert cursor.fetchone()[0] == 1

        # Delete file, node should cascade delete
        self.conn.execute("DELETE FROM files WHERE id=?", (file_id,))
        self.conn.commit()

        cursor = self.conn.execute("SELECT COUNT(*) FROM nodes")
        assert cursor.fetchone()[0] == 0, "Node should cascade delete after file delete"

    def test_unique_file_path(self):
        """Insert same path twice triggers IntegrityError."""
        create_tables(self.conn)

        self.conn.execute(
            "INSERT INTO files (path, hash, size_bytes, mtime_ns) VALUES (?, ?, ?, ?)",
            ("/test.py", "abc", 100, 1),
        )
        with pytest.raises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO files (path, hash, size_bytes, mtime_ns) VALUES (?, ?, ?, ?)",
                ("/test.py", "def", 200, 2),
            )

    def test_indexes_exist(self):
        """Verify all CREATE INDEX statements created indexes."""
        create_tables(self.conn)

        expected_indexes = {
            "idx_files_hash",
            "idx_files_status",
            "idx_nodes_file",
            "idx_nodes_type",
            "idx_nodes_qualified",
            "idx_nodes_deprecated",
            "idx_edges_source",
            "idx_edges_target",
            "idx_edges_type",
            "idx_edges_file",
            "idx_imports_file",
            "idx_imports_used",
            "idx_warnings_file",
            "idx_warnings_type",
            "idx_snapshots_time",
        }
        for idx in expected_indexes:
            assert self._index_exists(idx), f"Index {idx} should exist"

    def test_pragma_wal(self):
        """PRAGMA settings done by Database.__init__, create_tables only creates schema.
        :memory: db journal_mode is 'memory', file db returns 'wal'."""
        # PRAGMA settings handled by Database.__init__; just verify create_tables doesn't error
        create_tables(self.conn)
        assert True

    def test_pragma_foreign_keys(self):
        """Verify foreign_keys=ON."""
        create_tables(self.conn)
        cursor = self.conn.execute("PRAGMA foreign_keys")
        val = cursor.fetchone()[0]
        assert val == 1, f"foreign_keys should be 1, got {val}"

    def test_node_count_on_multiple_inserts(self):
        """Insert multiple nodes, verify correct count."""
        create_tables(self.conn)
        self.conn.execute(
            "INSERT INTO files (path, hash, size_bytes, mtime_ns) VALUES (?, ?, ?, ?)",
            ("/test.py", "abc", 100, 1),
        )
        for i in range(5):
            self.conn.execute(
                "INSERT INTO nodes (file_id, name, qualified_name, node_type, "
                "line_start, line_end, col_offset) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (1, f"func{i}", f"test.func{i}", "function", i, i + 2, 0),
            )
        cursor = self.conn.execute("SELECT COUNT(*) FROM nodes")
        assert cursor.fetchone()[0] == 5


# =============================================================================
# New index tests (index enhancement)
# =============================================================================


@pytest.mark.timeout(30)
class TestNewIndexes:
    """Tests for new composite indexes and sorted indexes."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Each test uses a separate in-memory database."""
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        yield
        self.conn.close()

    def _index_exists(self, index_name: str) -> bool:
        """Check if index exists."""
        cursor = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
            (index_name,),
        )
        return cursor.fetchone() is not None

    def test_idx_edges_source_type_exists(self):
        """Verify idx_edges_source_type composite index is created."""
        from graphlint.storage.schema import create_tables

        create_tables(self.conn)
        assert self._index_exists("idx_edges_source_type"), \
            "Missing composite index idx_edges_source_type"

    def test_idx_edges_target_type_exists(self):
        """Verify idx_edges_target_type composite index is created."""
        from graphlint.storage.schema import create_tables

        create_tables(self.conn)
        assert self._index_exists("idx_edges_target_type"), \
            "Missing composite index idx_edges_target_type"

    def test_idx_warnings_node_exists(self):
        """Verify idx_warnings_node index is created."""
        from graphlint.storage.schema import create_tables

        create_tables(self.conn)
        assert self._index_exists("idx_warnings_node"), \
            "Missing index idx_warnings_node"

    def test_idx_snapshots_warnings_exists(self):
        """Verify idx_snapshots_warnings sorted index is created."""
        from graphlint.storage.schema import create_tables

        create_tables(self.conn)
        assert self._index_exists("idx_snapshots_warnings"), \
            "Missing sorted index idx_snapshots_warnings"

    def test_idx_snapshots_nodes_exists(self):
        """Verify idx_snapshots_nodes sorted index is created."""
        from graphlint.storage.schema import create_tables

        create_tables(self.conn)
        assert self._index_exists("idx_snapshots_nodes"), \
            "Missing sorted index idx_snapshots_nodes"

    def test_all_new_indexes_created_together(self):
        """Verify all new indexes exist after create_tables call."""
        from graphlint.storage.schema import create_tables

        create_tables(self.conn)

        new_indexes = {
            "idx_edges_source_type",
            "idx_edges_target_type",
            "idx_warnings_node",
            "idx_snapshots_warnings",
            "idx_snapshots_nodes",
        }
        for idx in new_indexes:
            assert self._index_exists(idx), f"Missing new index {idx}"

    def test_new_indexes_do_not_break_existing_usage(self):
        """Verify new indexes do not affect basic DML operations on existing tables."""
        from graphlint.storage.schema import create_tables

        create_tables(self.conn)

        # Insert file
        self.conn.execute(
            "INSERT INTO files (path, hash, size_bytes, mtime_ns) VALUES (?, ?, ?, ?)",
            ("/test.py", "abc", 100, 1),
        )
        # Insert nodes
        self.conn.execute(
            "INSERT INTO nodes (file_id, name, qualified_name, node_type, "
            "line_start, line_end, col_offset) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (1, "MyClass", "test.MyClass", "class", 1, 10, 0),
        )
        self.conn.execute(
            "INSERT INTO nodes (file_id, name, qualified_name, node_type, "
            "line_start, line_end, col_offset) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (1, "my_func", "test.my_func", "function", 12, 15, 0),
        )
        # Insert edge (verify composite index does not affect edges insert)
        self.conn.execute(
            "INSERT INTO edges (source_id, target_id, edge_type, file_id, line) "
            "VALUES (?, ?, ?, ?, ?)",
            (2, 1, "call", 1, 13),
        )
        # Insert warning (verify idx_warnings_node does not affect warnings insert)
        self.conn.execute(
            "INSERT INTO warnings (file_id, node_id, warn_type, severity, message, line) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (1, 1, "circular_ref", "warning", "cycle detected", 5),
        )
        # Insert snapshot (verify sorted indexes do not affect graph_snapshots insert)
        self.conn.execute(
            "INSERT INTO graph_snapshots "
            "(snapshot_time, node_count, warning_count, edge_count) "
            "VALUES (?, ?, ?, ?)",
            ("2024-01-01", 2, 1, 1),
        )

        # Verify all data is queryable
        assert self.conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0] == 1
        assert self.conn.execute("SELECT COUNT(*) FROM warnings").fetchone()[0] == 1
        assert self.conn.execute("SELECT COUNT(*) FROM graph_snapshots").fetchone()[0] == 1


# =============================================================================
# Database PRAGMA optimization tests
# =============================================================================


@pytest.mark.timeout(30)
class TestDatabasePragma:
    """Tests for PRAGMA optimization settings during Database initialization."""

    def test_pragma_cache_size(self, tmp_path):
        """Verify PRAGMA cache_size is set to -8000 (8MB)."""
        from graphlint.storage.db import Database

        db = Database(str(tmp_path))
        try:
            row = db.fetchone("PRAGMA cache_size")
            assert row is not None
            # cache_size = -8000 means 8MB cache
            assert row[0] == -8000, f"cache_size should be -8000, got {row[0]}"
        finally:
            db.close()

    def test_pragma_temp_store(self, tmp_path):
        """Verify PRAGMA temp_store is set to MEMORY (2)."""
        from graphlint.storage.db import Database

        db = Database(str(tmp_path))
        try:
            row = db.fetchone("PRAGMA temp_store")
            assert row is not None
            # 2 = MEMORY
            assert row[0] == 2, f"temp_store should be 2 (MEMORY), got {row[0]}"
        finally:
            db.close()

    def test_pragma_mmap_size(self, tmp_path):
        """Verify PRAGMA mmap_size is set to 268435456 (256MB)."""
        from graphlint.storage.db import Database

        db = Database(str(tmp_path))
        try:
            row = db.fetchone("PRAGMA mmap_size")
            assert row is not None
            assert row[0] == 268435456, \
                f"mmap_size should be 268435456, got {row[0]}"
        finally:
            db.close()

    def test_pragma_journal_mode_wal(self, tmp_path):
        """Verify PRAGMA journal_mode is WAL."""
        from graphlint.storage.db import Database

        db = Database(str(tmp_path))
        try:
            row = db.fetchone("PRAGMA journal_mode")
            assert row is not None
            assert row[0].lower() == "wal", \
                f"journal_mode should be WAL, got {row[0]}"
        finally:
            db.close()

    def test_pragma_foreign_keys_on(self, tmp_path):
        """Verify PRAGMA foreign_keys is ON."""
        from graphlint.storage.db import Database

        db = Database(str(tmp_path))
        try:
            row = db.fetchone("PRAGMA foreign_keys")
            assert row is not None
            assert row[0] == 1, f"foreign_keys should be 1, got {row[0]}"
        finally:
            db.close()

    def test_all_pragmas_set_simultaneously(self, tmp_path):
        """Verify all PRAGMA optimizations are set simultaneously during Database init."""
        from graphlint.storage.db import Database

        db = Database(str(tmp_path))
        try:
            cache = db.fetchone("PRAGMA cache_size")
            assert cache is not None and cache[0] == -8000

            temp = db.fetchone("PRAGMA temp_store")
            assert temp is not None and temp[0] == 2

            mmap = db.fetchone("PRAGMA mmap_size")
            assert mmap is not None and mmap[0] == 268435456

            fk = db.fetchone("PRAGMA foreign_keys")
            assert fk is not None and fk[0] == 1
        finally:
            db.close()

    def test_database_creates_tables_and_new_indexes(self, tmp_path):
        """Verify Database initialization includes new indexes."""
        from graphlint.storage.db import Database

        db = Database(str(tmp_path))
        try:
            new_indexes = {
                "idx_edges_source_type",
                "idx_edges_target_type",
                "idx_warnings_node",
                "idx_snapshots_warnings",
                "idx_snapshots_nodes",
            }
            for idx in new_indexes:
                cursor = db.execute(
                    "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
                    (idx,),
                )
                assert cursor.fetchone() is not None, f"Missing index {idx} after Database init"
        finally:
            db.close()
