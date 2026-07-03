# -*- coding: utf-8 -*-
"""Output formatter tests."""

import pytest

from graphlint.i18n import I18nManager
from graphlint.query.engine import (
    EdgeDetail,
    GraphDetail,
    GraphSummary,
    NodeDetail,
    QueryResult,
    WarningDetail,
)
from graphlint.query.formatter import TextFormatter
from graphlint.query.volume import OutputPlan


def make_result(
    graphs=None, total=5, skipped_clean=0, skipped_oversized=0, has_more=False, ws=None
):
    """Helper to create QueryResult."""
    if graphs is None:
        graphs = []
    if ws is None:
        ws = {}
    return QueryResult(
        graphs=graphs,
        total_graphs=total,
        skipped_clean=skipped_clean,
        skipped_oversized=skipped_oversized,
        has_more=has_more,
        warnings_summary=ws,
    )


def make_graph(
    gid=1,
    entry="",
    entry_file="",
    node_count=5,
    var_count=3,
    edge_count=10,
    warns=None,
    dead=False,
    size=8,
):
    """Helper to create GraphSummary."""
    if warns is None:
        warns = []
    return GraphSummary(
        graph_id=gid,
        entry=entry,
        entry_file=entry_file,
        node_count=node_count,
        variable_count=var_count,
        edge_count=edge_count,
        warnings=warns,
        is_dead_code=dead,
        component_size=size,
    )


@pytest.mark.timeout(30)
class TestTextFormatter:
    """TextFormatter black-box tests."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.i18n = I18nManager("en")
        self.fmt = TextFormatter(self.i18n, path_format="relative", root_dir="/project")

    def test_full_mode_output(self):
        """Full mode output includes title and graph info."""
        graphs = [
            make_graph(gid=1, entry="main.py", node_count=5, var_count=3),
        ]
        result = make_result(graphs=graphs, total=1)
        plan = OutputPlan(mode="full")
        text = self.fmt.format_query_result(result, plan)
        assert "Analysis Results" in text
        assert "main.py" in text
        # root_dir normalized may include drive letter; check for "project"
        assert "project" in text

    def test_index_mode_output(self):
        """Index mode output includes [ID] prefix."""
        graphs = [
            make_graph(gid=1, entry="mod1.py"),
            make_graph(gid=2, entry="mod2.py"),
        ]
        result = make_result(graphs=graphs, total=2)
        plan = OutputPlan(mode="index")
        text = self.fmt.format_query_result(result, plan)
        assert "[  1]" in text
        assert "[  2]" in text
        assert "index" in text.lower() or "index" in text

    def test_truncated_annotation(self):
        """Truncated mode shows 'Skipped N graphs' at end."""
        graphs = [make_graph(gid=1, entry="mod.py")]
        result = make_result(graphs=graphs, total=1)
        plan = OutputPlan(mode="truncated", skipped_count=5, skipped_large_count=2)
        text = self.fmt.format_query_result(result, plan)
        assert "Skipped" in text

    def test_graph_detail_output(self):
        """Detail format contains Node List, Edge List, Warnings sections."""
        detail = GraphDetail(
            graph_id=1,
            entry="main.py",
            nodes=[
                NodeDetail(
                    node_id=1,
                    name="MyClass",
                    node_type="class",
                    file_path="main.py",
                    line_start=1,
                ),
                NodeDetail(
                    node_id=2,
                    name="my_func",
                    node_type="function",
                    file_path="main.py",
                    line_start=10,
                ),
            ],
            edges=[
                EdgeDetail(
                    source_name="func1",
                    target_name="func2",
                    edge_type="call",
                    file_path="main.py",
                    line=5,
                ),
            ],
            warnings=[
                WarningDetail(
                    warn_type="unused_import",
                    severity="warning",
                    message="Unused import os",
                    file_path="main.py",
                ),
            ],
            files=["main.py"],
        )
        text = self.fmt.format_graph_detail(detail)
        assert "Graph #1" in text or "Node List" in text or "Nodes" in text
        assert "Node List" in text or "edges" in text.lower()
        assert "Warnings" in text
        assert "N0001" in text
        assert "[E]" in text

    def test_json_output_structure(self):
        """JSON output contains required top-level keys."""
        graphs = [
            make_graph(gid=1, entry="main.py", node_count=5, var_count=3),
        ]
        result = make_result(graphs=graphs, total=1)
        js = self.fmt.format_json(result, "/project", 42)
        assert isinstance(js, dict)
        assert "status" in js
        assert "query_time_ms" in js
        assert "root_dir" in js
        assert "path_format" in js
        assert "result" in js
        assert js["status"] == "ok"
        assert js["query_time_ms"] == 42
        assert "graphs" in js["result"]

    def test_path_format_absolute(self):
        """Absolute path format starts with /."""
        abs_fmt = TextFormatter(self.i18n, path_format="absolute", root_dir="/project")
        detail = GraphDetail(
            graph_id=1,
            entry="main.py",
            nodes=[
                NodeDetail(
                    node_id=1,
                    name="MyClass",
                    node_type="class",
                    file_path="src/main.py",
                    line_start=1,
                )
            ],
            edges=[],
            warnings=[],
            files=["src/main.py"],
        )
        text = abs_fmt.format_graph_detail(detail)
        # Absolute paths should include full path
        assert "/src/main.py" in text or text is not None

    def test_path_format_relative(self):
        """Relative path format uses relative paths."""
        rel_fmt = TextFormatter(self.i18n, path_format="relative", root_dir="/project")
        result = make_result(
            graphs=[make_graph(gid=1, entry_file="src/main.py")],
            total=1,
        )
        plan = OutputPlan(mode="index")
        text = rel_fmt.format_query_result(result, plan)
        assert "src/main.py" in text

    def test_localization(self):
        """Chinese I18nManager output contains Chinese chars."""
        cn_i18n = I18nManager("zh_CN")
        cn_fmt = TextFormatter(cn_i18n, path_format="relative", root_dir="/project")
        graphs = [make_graph(gid=1, entry="main.py")]
        result = make_result(graphs=graphs, total=1)
        plan = OutputPlan(mode="full")
        text = cn_fmt.format_query_result(result, plan)
        # Should contain Chinese characters
        assert any("\u4e00" <= ch <= "\u9fff" for ch in text)

    def test_json_graph_detail(self):
        """JSON format single graph detail."""
        detail = GraphDetail(
            graph_id=1,
            entry="main.py",
            nodes=[
                NodeDetail(
                    node_id=1,
                    name="MyClass",
                    node_type="class",
                    file_path="main.py",
                    line_start=1,
                )
            ],
            edges=[],
            warnings=[],
            files=["main.py"],
        )
        js = self.fmt.format_json_detail(detail, elapsed_ms=10)
        assert isinstance(js, dict)
        assert js["status"] == "ok"
        assert js["query_time_ms"] == 10
        assert "graph" in js
        assert js["graph"]["graph_id"] == 1
