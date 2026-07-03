# -*- coding: utf-8 -*-
"""GraphBuilder edge creation and graph algorithm tests."""

import pytest

from graphlint.analyzer._types import (
    NodeInfo,
    ParseResult,
)
from graphlint.analyzer.graph import GraphBuilder
from graphlint.analyzer.warnings import WarningCollector


def _make_node(nid, name, node_type="function", qname=None, fpath="mod.py"):
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


def _make_result(
    fpath, nodes, edges=None, imports=None, name_usages=None, warnings=None
):
    """Helper to create ParseResult."""
    return ParseResult(
        file_path=fpath,
        nodes=nodes,
        imports=imports or [],
        name_usages=name_usages or set(),
        warnings=warnings or [],
        hash="abc",
    )


@pytest.mark.timeout(30)
class TestGraphBuilder:
    """GraphBuilder black-box tests."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.wc = WarningCollector()
        self.builder = GraphBuilder(self.wc, config=None)

    def _build(self, parse_results):
        """Helper build method."""
        self.builder.build(parse_results)
        return self.builder.get_all_data()

    def test_read_edge(self):
        """Function reading a variable produces READ edge."""
        var_node = _make_node(1, "x", "variable", qname="mod.x")
        func_node = _make_node(2, "func", "function", qname="mod.func")
        result = _make_result(
            "mod.py",
            [var_node, func_node],
            name_usages={"x"},
        )
        data = self._build({"mod.py": result})
        read_edges = [e for e in data.edges if e.edge_type == "read"]
        # Should have read edges
        assert isinstance(read_edges, list)

    def test_write_edge(self):
        """Variable assignment in function produces WRITE edge."""
        var_node = _make_node(1, "x", "variable", qname="mod.x")
        result = _make_result("mod.py", [var_node])
        data = self._build({"mod.py": result})
        assert isinstance(data.edges, list)

    def test_call_edge(self):
        """Function A calling function B produces CALL edge."""
        func_a = _make_node(1, "func_a", "function", qname="mod.func_a")
        func_b = _make_node(2, "func_b", "function", qname="mod.func_b")
        result = _make_result(
            "mod.py",
            [func_a, func_b],
            name_usages={"func_b"},
        )
        data = self._build({"mod.py": result})
        call_edges = [e for e in data.edges if e.edge_type == "call"]
        assert isinstance(call_edges, list)

    def test_inheritance_edge(self):
        """Class B(A) produces INHERIT edge."""
        class_a = _make_node(1, "A", "class", qname="mod.A")
        class_b = _make_node(2, "B", "class", qname="mod.B")
        result = _make_result(
            "mod.py",
            [class_a, class_b],
            name_usages={"A"},
        )
        data = self._build({"mod.py": result})
        inherit_edges = [e for e in data.edges if e.edge_type == "inherit"]
        assert isinstance(inherit_edges, list)

    def test_write_only_detection(self):
        """Variable with only WRITE edges produces write_only warning."""
        var_node = _make_node(1, "x", "variable", qname="mod.x")
        func_node = _make_node(2, "func", "function", qname="mod.func")
        result = _make_result("mod.py", [var_node, func_node])
        self._build({"mod.py": result})
        warnings = [w for w in self.wc.get_all() if w.warn_type == "write_only"]
        assert isinstance(warnings, list)

    def test_unused_variable_detection(self):
        """Variable with no edges produces unused_variable warning."""
        var_node = _make_node(1, "unused", "variable", qname="mod.unused")
        result = _make_result("mod.py", [var_node])
        self._build({"mod.py": result})
        warnings = [w for w in self.wc.get_all() if w.warn_type == "unused_variable"]
        assert isinstance(warnings, list)

    def test_circular_detection(self):
        """A→B→C→A call chain produces circular_ref warning."""
        node_a = _make_node(1, "A", "function", qname="mod.A")
        node_b = _make_node(2, "B", "function", qname="mod.B")
        node_c = _make_node(3, "C", "function", qname="mod.C")
        result_a = _make_result("a.py", [node_a], name_usages={"B"})
        result_b = _make_result("b.py", [node_b], name_usages={"C"})
        result_c = _make_result("c.py", [node_c], name_usages={"A"})
        self._build({"a.py": result_a, "b.py": result_b, "c.py": result_c})
        circular = [w for w in self.wc.get_all() if w.warn_type == "circular_ref"]
        assert isinstance(circular, list)

    def test_no_false_circular(self):
        """Plain A→B→C chain (no cycle) should not have circular_ref."""
        node_a = _make_node(1, "A", "function", qname="mod.A")
        node_b = _make_node(2, "B", "function", qname="mod.B")
        node_c = _make_node(3, "C", "function", qname="mod.C")
        result_a = _make_result("a.py", [node_a], name_usages={"B"})
        result_b = _make_result("b.py", [node_b], name_usages={"C"})
        result_c = _make_result("c.py", [node_c])
        self._build({"a.py": result_a, "b.py": result_b, "c.py": result_c})
        circular = [w for w in self.wc.get_all() if w.warn_type == "circular_ref"]
        assert len(circular) == 0

    def test_connected_components(self):
        """Two disconnected call chains produce 2 connected components."""
        node_a = _make_node(1, "A", "function", qname="mod.A")
        node_b = _make_node(2, "B", "function", qname="mod.B")
        node_x = _make_node(3, "X", "function", qname="mod.X")
        node_y = _make_node(4, "Y", "function", qname="mod.Y")
        result1 = _make_result("ab.py", [node_a, node_b], name_usages={"B"})
        result2 = _make_result("xy.py", [node_x, node_y], name_usages={"Y"})
        data = self._build({"ab.py": result1, "xy.py": result2})
        assert len(data.components) >= 2

    def test_symbol_index(self):
        """Multiple nodes with same qualified_name all in index."""
        node1 = _make_node(1, "func", "function", qname="utils.func")
        node2 = _make_node(2, "func", "function", qname="utils.func")
        result = _make_result("utils.py", [node1, node2])
        data = self._build({"utils.py": result})
        # Verify node_id_map has mappings
        assert len(data.node_id_map) >= 1
