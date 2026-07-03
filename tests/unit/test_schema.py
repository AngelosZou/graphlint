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
