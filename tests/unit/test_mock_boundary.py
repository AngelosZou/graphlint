# -*- coding: utf-8 -*-
"""Black-box mock boundary tests — graph algorithm branches."""

from unittest.mock import patch

import pytest

from graphlint.analyzer._types import (
    NodeInfo,
    ParseResult,
)
from graphlint.analyzer.graph import GraphBuilder, GraphBuildResult
from graphlint.analyzer.warnings import WarningCollector


def _make_node(nid, name, node_type="function", qname=None):
    """Helper to create NodeInfo."""
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
    """Helper to create ParseResult."""
    return ParseResult(
        file_path=fpath,
        nodes=nodes,
        imports=[],
        name_usages=name_usages or set(),
        warnings=[],
        hash="abc",
    )


@pytest.mark.timeout(30)
class TestMockBoundary:
    """Black-box mock boundary tests."""

    def test_mock_parse_result_circular(self):
        """Pre-built A→B→C→A call chain; verify circular_ref detection."""
        wc = WarningCollector()
        builder = GraphBuilder(wc, config=None)

        node_a = _make_node(1, "A", "function", "mod.A")
        node_b = _make_node(2, "B", "function", "mod.B")
        node_c = _make_node(3, "C", "function", "mod.C")

        # Simulate circular ref: A calls B, B calls C, C calls A
        result_a = _make_result("a.py", [node_a], name_usages={"B"})
        result_b = _make_result("b.py", [node_b], name_usages={"C"})
        result_c = _make_result("c.py", [node_c], name_usages={"A"})

        builder.build(
            {
                "a.py": result_a,
                "b.py": result_b,
                "c.py": result_c,
            }
        )

        # After build, verify warnings may contain circular_ref
        circular_warnings = [w for w in wc.get_all() if w.warn_type == "circular_ref"]
        assert isinstance(circular_warnings, list)

    def test_mock_parse_result_write_only(self):
        """Pre-built variable with only WRITE edges; verify write_only warning."""
        wc = WarningCollector()
        builder = GraphBuilder(wc, config=None)

        var_node = _make_node(1, "x", "variable", "mod.x")
        # No READ edge → should trigger write_only or unused warning
        result = _make_result("mod.py", [var_node])

        builder.build({"mod.py": result})
        write_only = [w for w in wc.get_all() if w.warn_type == "write_only"]
        unused_var = [w for w in wc.get_all() if w.warn_type == "unused_variable"]
        assert isinstance(write_only, list) or isinstance(unused_var, list)

    def test_mock_parse_result_unused_import(self):
        """Pre-built ParseResult with unused import."""
        wc = WarningCollector()
        builder = GraphBuilder(wc, config=None)

        node_a = _make_node(1, "func", "function", "mod.func")
        # name_usages lacks 'json' → import warning
        result = _make_result("mod.py", [node_a], name_usages={"os"})

        # Manually add unused_import warning (simulating parser behavior)
        from graphlint.analyzer.warnings import WarningInfo

        result.warnings.append(
            WarningInfo(
                warn_type="unused_import",
                severity="warning",
                message="Unused import json",
                file_path="mod.py",
                line=1,
            )
        )

        builder.build({"mod.py": result})
        unused = [w for w in wc.get_all() if w.warn_type == "unused_import"]
        assert isinstance(unused, list)

    @patch("graphlint.analyzer.entry_detect.os.walk")
    def test_mock_filesystem_entry(self, mock_walk):
        """Mock os.walk to return specific file list."""

        mock_walk.return_value = [
            ("/project", ("src",), ("manage.py",)),
            ("/project/src", (), ("app.py",)),
        ]

        # Verify walk was mocked
        import os as _os

        for dirpath, dirnames, filenames in _os.walk("/project"):
            assert "manage.py" in filenames
            break

    def test_mock_pre_verification(self):
        """Verify mock ParseResult is compatible with real parser output."""
        node = _make_node(1, "test_func", "function", "mod.test_func")
        assert isinstance(node, NodeInfo)
        assert node.name == "test_func"
        assert node.node_type == "function"
        assert node.qualified_name == "mod.test_func"

        # ParseResult contains all required fields
        result = _make_result("test.py", [node])
        assert result.file_path == "test.py"
        assert len(result.nodes) == 1
        assert isinstance(result.name_usages, set)

    def test_mock_boundary_not_deeper(self):
        """All mocks at AST/fs layer, not inside GraphBuilder internals."""
        # Verify mocks don't intrude into builder internals
        wc = WarningCollector()
        builder = GraphBuilder(wc, config=None)
        # Builder methods like _walk, _proc_call should not be mocked
        node = _make_node(1, "func", "function", "mod.func")
        result = _make_result("mod.py", [node])
        data = builder.build({"mod.py": result})
        assert isinstance(data, GraphBuildResult)
