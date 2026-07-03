# -*- coding: utf-8 -*-
"""Data transfer pipeline tests."""

import os
import sqlite3

import pytest

from graphlint.analyzer._types import NodeInfo, ParseResult
from graphlint.analyzer.graph import GraphBuilder
from graphlint.analyzer.warnings import WarningCollector


def _make_node(nid, name, node_type="function", qname=None):
    return NodeInfo(
        id=nid,
        file_id=1,
        name=name,
        qualified_name=qname or f"mod.{name}",
        node_type=node_type,
        line_start=1,
        line_end=5,
        col_offset=0,
        parent_node_id=None,
        is_deprecated=False,
        deprecation_msg="",
        type_annotation="",
        is_async=False,
        decorators=[],
        docstring="",
        is_entry=False,
    )


def _make_result(fpath, nodes, name_usages=None):
    return ParseResult(
        file_path=fpath,
        nodes=nodes,
        imports=[],
        name_usages=name_usages or set(),
        warnings=[],
        hash="abc",
    )


@pytest.mark.timeout(30)
class TestDataTransfer:
    """Data transfer pipeline tests."""

    def test_data_transfer_parse_to_graphbuilder(self):
        """Mock SourceParser, feed into GraphBuilder."""
        wc = WarningCollector()
        builder = GraphBuilder(wc, config=None)

        node_a = _make_node(1, "func_a", "function", "mod.func_a")
        node_b = _make_node(2, "func_b", "function", "mod.func_b")
        result = _make_result("mod.py", [node_a, node_b], name_usages={"func_b"})

        data = builder.build({"mod.py": result})
        assert len(data.nodes) >= 2
        assert isinstance(data.edges, list)

    def test_data_transfer_graphbuilder_to_sqlite(self):
        """Use :memory: SQLite, run GraphBuilder.build()."""
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS files (id INTEGER PRIMARY KEY, path TEXT, hash TEXT, size_bytes INTEGER, mtime_ns INTEGER)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS nodes (id INTEGER PRIMARY KEY, file_id INTEGER, name TEXT, qualified_name TEXT, node_type TEXT, line_start INTEGER, line_end INTEGER, col_offset INTEGER)"
        )

        wc = WarningCollector()
        builder = GraphBuilder(wc, config=None)
        node_a = _make_node(1, "func_a", "function", "mod.func_a")
        result = _make_result("mod.py", [node_a])

        data = builder.build({"mod.py": result})

        # Insert nodes into SQLite
        for n in data.nodes:
            conn.execute(
                "INSERT INTO nodes (id, file_id, name, qualified_name, node_type, line_start, line_end, col_offset) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    n.id,
                    n.file_id,
                    n.name,
                    n.qualified_name,
                    n.node_type,
                    n.line_start,
                    n.line_end,
                    n.col_offset,
                ),
            )
        conn.commit()

        cursor = conn.execute("SELECT COUNT(*) FROM nodes")
        count = cursor.fetchone()[0]
        assert count >= 1
        conn.close()

    def test_data_transfer_query_to_format(self):
        """Pre-built QueryResult, TextFormatter.format_query_result()."""
        from graphlint.i18n import I18nManager
        from graphlint.query.engine import GraphSummary, QueryResult
        from graphlint.query.formatter import TextFormatter
        from graphlint.query.volume import OutputPlan

        i18n = I18nManager("en")
        fmt = TextFormatter(i18n, path_format="relative", root_dir="/project")

        gs = GraphSummary(
            graph_id=1,
            entry="main.py",
            entry_file="main.py",
            node_count=5,
            variable_count=3,
            edge_count=8,
            warnings=["unused_import"],
            is_dead_code=False,
        )
        result = QueryResult(graphs=[gs], total_graphs=1)
        plan = OutputPlan(mode="full")
        text = fmt.format_query_result(result, plan)
        assert "Analysis Results" in text or "graphlint" in text
        assert "main.py" in text

    def test_data_transfer_end_to_end_mock_fs(self):
        """Mock filesystem, run full build→query pipeline."""
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create simple project files
            src_dir = os.path.join(tmpdir, "src")
            os.makedirs(src_dir)
            with open(os.path.join(src_dir, "main.py"), "w") as f:
                f.write("import os\n\ndef greet():\n    print('hello')\n\ngreet()\n")

            from graphlint.api import build, query

            # Build
            result = build(root_dir=tmpdir, force_rebuild=True, parallel=1)
            assert isinstance(result, dict)
            assert "files_scanned" in result or "duration_ms" in result

            # Query
            result2 = query(root_dir=tmpdir, json_output=False)
            assert isinstance(result2, str) or isinstance(result2, dict)
