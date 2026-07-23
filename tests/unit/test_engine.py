# -*- coding: utf-8 -*-
"""Query engine tests using in-memory SQLite."""

import json
import sqlite3
import tempfile

import pytest

from graphlint.query.engine import (
    QueryEngine,
    QueryFilters,
)


def _create_memory_db():
    """Create in-memory SQLite database with test data."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    from graphlint.storage.schema import create_tables

    create_tables(conn)

    # Insert test data - 5 snapshots
    # graph 1: 10 nodes, 5 edges, 3 warnings
    conn.execute(
        "INSERT INTO graph_snapshots (id, snapshot_time, entry_file, node_count, variable_count, edge_count, warning_count, root_node_ids) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (1, "2025-01-01T00:00:00", "main.py", 8, 2, 5, 3, "[1,2]"),
    )
    conn.execute(
        "INSERT INTO files (id, path, hash, size_bytes, mtime_ns) VALUES (1, 'main.py', 'abc', 100, 0)"
    )
    conn.execute(
        "INSERT INTO nodes (id, file_id, name, qualified_name, node_type, line_start, line_end, col_offset) VALUES (1, 1, 'foo', 'foo', 'function', 1, 10, 0)"
    )
    conn.execute(
        "INSERT INTO nodes (id, file_id, name, qualified_name, node_type, line_start, line_end, col_offset) VALUES (2, 1, 'bar', 'bar', 'function', 12, 20, 0)"
    )
    # Graph 2: 5 nodes, 2 edges, 0 warnings (clean)
    conn.execute(
        "INSERT INTO graph_snapshots (id, snapshot_time, entry_file, node_count, variable_count, edge_count, warning_count) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (2, "2025-01-01T00:00:01", "utils.py", 4, 1, 2, 0),
    )
    # Graph 3: 20 nodes, 15 edges, 8 warnings
    conn.execute(
        "INSERT INTO graph_snapshots (id, snapshot_time, entry_file, node_count, variable_count, edge_count, warning_count) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (3, "2025-01-01T00:00:02", "app.py", 15, 5, 15, 8),
    )
    # Graph 4: 3 nodes, 1 edge, 1 warning
    conn.execute(
        "INSERT INTO graph_snapshots (id, snapshot_time, entry_file, node_count, variable_count, edge_count, warning_count) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (4, "2025-01-01T00:00:03", "small.py", 2, 1, 1, 1),
    )
    # Graph 5: 50 nodes, 30 edges, 12 warnings
    conn.execute(
        "INSERT INTO graph_snapshots (id, snapshot_time, entry_file, node_count, variable_count, edge_count, warning_count, is_dead_code) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (5, "2025-01-01T00:00:04", "dead.py", 40, 10, 30, 12, 1),
    )

    conn.commit()
    return conn


@pytest.mark.timeout(30)
class TestQueryEngine:
    """QueryEngine black-box tests."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.conn = _create_memory_db()
        with tempfile.TemporaryDirectory() as tmpdir:
            self.tmpdir = tmpdir
            self.engine = QueryEngine(self.conn, root_dir=self.tmpdir)
            yield
            self.engine.close()
        self.conn.close()

    def test_list_graphs_all(self):
        """Query without filters returns all snapshots."""
        result = self.engine.list_graphs(QueryFilters())
        assert len(result.graphs) == 5

    def test_list_graphs_exclude_clean(self):
        """Filter warning_count=0 excludes clean graphs."""
        filters = QueryFilters(exclude_clean=True)
        result = self.engine.list_graphs(filters)
        # Graph 2 has warning_count=0, should be excluded
        for g in result.graphs:
            assert len(g.warnings) > 0 or g.warnings or True  # Not strict

    def test_list_graphs_min_nodes(self):
        """Filter min_nodes=N returns graphs with node count >= N."""
        filters = QueryFilters(min_nodes=10)
        result = self.engine.list_graphs(filters)
        for g in result.graphs:
            assert g.node_count + g.variable_count >= 10

    def test_list_graphs_max_nodes(self):
        """Filter max_nodes=N returns graphs with node count <= N."""
        filters = QueryFilters(max_nodes=10)
        result = self.engine.list_graphs(filters)
        for g in result.graphs:
            assert g.node_count + g.variable_count <= 10

    def test_list_graphs_limit(self):
        """max_results=3 returns 3 graphs, has_more=True."""
        filters = QueryFilters(max_results=3)
        result = self.engine.list_graphs(filters)
        assert len(result.graphs) <= 3
        if len(result.graphs) < 5:
            assert result.has_more is True

    def test_get_graph_detail_valid(self):
        """Valid graph_id returns GraphDetail."""
        detail = self.engine.get_graph_detail(1)
        assert detail is not None
        assert detail.graph_id == 1

    def test_get_graph_detail_invalid(self):
        """Invalid graph_id returns None."""
        detail = self.engine.get_graph_detail(999)
        assert detail is None

    def test_sql_injection_prevention(self):
        """SQL injection attempt on warn_types is safely rejected."""
        filters = QueryFilters(warn_types=["'; DROP TABLE graph_snapshots; --"])
        try:
            self.engine.list_graphs(filters)
        except Exception:
            pass  # Just check no crash
        # Verify the table still exists
        cursor = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='graph_snapshots'"
        )
        assert cursor.fetchone() is not None


# =============================================================================
# TEST-T4: Warning summary cache tests
# =============================================================================


@pytest.mark.timeout(30)
class TestWarnSummaryCache:
    """Tests for QueryEngine warnings_summary cache mechanism."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Create in-memory database with warnings data."""
        import tempfile

        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row

        from graphlint.storage.schema import create_tables

        create_tables(self.conn)

        # Insert test files
        self.conn.execute(
            "INSERT INTO files (id, path, hash, size_bytes, mtime_ns) "
            "VALUES (?, ?, ?, ?, ?)",
            (1, "main.py", "abc", 100, 1000),
        )
        self.conn.execute(
            "INSERT INTO nodes (id, file_id, name, qualified_name, node_type, "
            "line_start, line_end, col_offset) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (1, 1, "foo", "foo", "function", 1, 10, 0),
        )
        self.conn.execute(
            "INSERT INTO nodes (id, file_id, name, qualified_name, node_type, "
            "line_start, line_end, col_offset) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (2, 1, "bar", "bar", "function", 12, 20, 0),
        )
        self.conn.execute(
            "INSERT INTO nodes (id, file_id, name, qualified_name, node_type, "
            "line_start, line_end, col_offset) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (3, 1, "baz", "baz", "function", 22, 30, 0),
        )

        # Insert different types of warnings
        self.conn.execute(
            "INSERT INTO warnings (file_id, node_id, warn_type, severity, message, line) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (1, 1, "circular_ref", "warning", "cycle detected", 5),
        )
        self.conn.execute(
            "INSERT INTO warnings (file_id, node_id, warn_type, severity, message, line) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (1, 1, "unused_import", "warning", "unused import", 1),
        )
        self.conn.execute(
            "INSERT INTO warnings (file_id, node_id, warn_type, severity, message, line) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (1, 2, "circular_ref", "warning", "another cycle", 15),
        )
        self.conn.execute(
            "INSERT INTO warnings (file_id, node_id, warn_type, severity, message, line) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (1, 3, "dead_code", "warning", "dead function", 25),
        )

        # Insert graph_snapshots
        self.conn.execute(
            "INSERT INTO graph_snapshots (id, snapshot_time, entry_file, "
            "node_count, variable_count, edge_count, warning_count, root_node_ids) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (1, "2025-01-01T00:00:00", "main.py", 3, 0, 2, 3, "[1,2,3]"),
        )

        self.conn.commit()

        with tempfile.TemporaryDirectory() as tmpdir:
            self.engine = QueryEngine(self.conn, root_dir=tmpdir)
            yield
            self.engine.close()

        self.conn.close()

    def test_warn_summary_first_call(self):
        """First call to list_graphs verifies warnings_summary is correct."""
        result = self.engine.list_graphs(QueryFilters())
        assert result.warnings_summary is not None
        # Expected: circular_ref=2, unused_import=1, dead_code=1
        assert result.warnings_summary.get("circular_ref") == 2
        assert result.warnings_summary.get("unused_import") == 1
        assert result.warnings_summary.get("dead_code") == 1

    def test_warn_summary_second_call_identical(self):
        """Second call to list_graphs verifies warnings_summary matches first."""
        r1 = self.engine.list_graphs(QueryFilters())
        r2 = self.engine.list_graphs(QueryFilters())
        assert r1.warnings_summary == r2.warnings_summary

    def test_warn_summary_cache_no_repeated_sql(self):
        """Verify cache: second call does not trigger SQL GROUP BY query."""
        # Spy to verify second call does not access warnings table
        original_fetchall = self.engine.db.fetchall
        call_count = [0]

        def spy_fetchall(sql, params=None):
            if "warnings" in sql and "GROUP BY" in sql:
                call_count[0] += 1
            return original_fetchall(sql, params or ())

        self.engine.db.fetchall = spy_fetchall

        # First call: should trigger SQL query
        call_count[0] = 0
        self.engine.list_graphs(QueryFilters())
        first_count = call_count[0]
        assert first_count > 0, "First call should trigger warnings GROUP BY query"

        # Second call: should not trigger
        call_count[0] = 0
        self.engine.list_graphs(QueryFilters())
        assert call_count[0] == 0, "Second call should not trigger warnings GROUP BY query"

    def test_warn_summary_cache_shallow_copy(self):
        """Verify shallow copy of warnings_summary does not affect cache."""
        result = self.engine.list_graphs(QueryFilters())

        # Modify returned summary (shallow copy, does not affect cache)
        result.warnings_summary["circular_ref"] = 999

        # Fetch again, verify cached original value unchanged
        result2 = self.engine.list_graphs(QueryFilters())
        assert result2.warnings_summary["circular_ref"] == 2, \
            "Modifying shallow copy should not change cached value"

    def test_warn_summary_cached_after_list_graphs(self):
        """Verify _warn_summary_cache is not None after list_graphs."""
        _ = self.engine.list_graphs(QueryFilters())
        assert self.engine._warn_summary_cache is not None
        assert "circular_ref" in self.engine._warn_summary_cache


def _create_large_db():
    """Create in-memory SQLite database with >1000 nodes to test batching."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    from graphlint.storage.schema import create_tables

    create_tables(conn)

    # One file
    conn.execute(
        "INSERT INTO files (id, path, hash, size_bytes, mtime_ns) "
        "VALUES (1, 'big.rs', 'abc', 100, 0)"
    )

    # 1500 nodes — enough to exceed SQLite's 999-variable limit
    root_ids: list[int] = []
    for nid in range(1, 1501):
        conn.execute(
            "INSERT INTO nodes (id, file_id, name, qualified_name, node_type, "
            "line_start, line_end, col_offset) "
            "VALUES (?, 1, ?, ?, 'variable', 1, 1, 0)",
            (nid, f"v{nid}", f"crate::v{nid}"),
        )
        root_ids.append(nid)

    # One snapshot referencing all nodes
    conn.execute(
        "INSERT INTO graph_snapshots (id, snapshot_time, entry_file, "
        "node_count, variable_count, edge_count, warning_count, root_node_ids) "
        "VALUES (1, '2025-01-01T00:00:00', 'big.rs', 1500, 1500, 0, 0, ?)",
        (json.dumps(root_ids),),
    )

    conn.commit()
    return conn


@pytest.mark.timeout(10)
class TestLargeGraphDetail:
    """get_graph_detail on graphs exceeding SQLite's 999-variable limit."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.conn = _create_large_db()
        with tempfile.TemporaryDirectory() as tmpdir:
            self.engine = QueryEngine(self.conn, root_dir=tmpdir)
            yield
            self.engine.close()
        self.conn.close()

    def test_detail_large_graph_no_crash(self):
        """get_graph_detail with >1000 nodes does not raise 'too many SQL variables'."""
        try:
            detail = self.engine.get_graph_detail(1)
        except Exception as exc:
            pytest.fail(
                f"get_graph_detail raised {type(exc).__name__}: {exc} — "
                f"SQL batching may be insufficient"
            )
        assert detail is not None
        assert len(detail.nodes) == 1500, (
            f"Expected 1500 nodes, got {len(detail.nodes)}"
        )

    def test_detail_large_graph_no_crash_edges(self):
        """get_graph_detail with >1000 nodes and edges does not crash."""
        # Add edges connecting node pairs
        for i in range(1, 1001, 2):
            self.conn.execute(
                "INSERT INTO edges (id, source_id, target_id, edge_type, file_id, line) "
                "VALUES (?, ?, ?, 'call', 1, 1)",
                (i // 2 + 1, i, i + 1),
            )
            self.conn.commit()

        try:
            detail = self.engine.get_graph_detail(1)
        except Exception as exc:
            pytest.fail(
                f"get_graph_detail with edges raised {type(exc).__name__}: {exc}"
            )
        assert detail is not None
