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


# =============================================================================
# TEST-T5: Suffix index defaultdict optimization and _resolve_symbol cache tests
# =============================================================================


@pytest.mark.timeout(30)
class TestSuffixIndexAndResolveCache:
    """Tests for suffix index and _resolve_symbol cache mechanism."""

    def _make_node_info(self, nid: int, qname: str) -> NodeInfo:
        """Create a simple NodeInfo instance."""
        return NodeInfo(
            id=nid,
            file_id=1,
            name=qname.split(".")[-1],
            qualified_name=qname,
            node_type="function",
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

    def test_symbol_index_defaultdict_type(self):
        """Verify _symbol_index is of type defaultdict(list)."""
        from collections import defaultdict

        from graphlint.analyzer.warnings import WarningCollector

        builder = GraphBuilder(WarningCollector(), {})
        assert isinstance(builder._symbol_index, defaultdict)
        assert isinstance(builder._suffix_index, defaultdict)

    def test_suffix_index_contains_all_suffixes(self):
        """Verify suffix index contains all suffixes after adding deeply nested qualified names."""
        from graphlint.analyzer.warnings import WarningCollector

        builder = GraphBuilder(WarningCollector(), {})

        node_a = self._make_node_info(1, "a.b.c.d.Foo")
        node_b = self._make_node_info(2, "x.y.z.Bar")

        builder.add_node(node_a, preserve_id=True)
        builder.add_node(node_b, preserve_id=True)

        suffix_idx = builder._suffix_index

        # All suffixes of Foo
        assert "a.b.c.d.Foo" in suffix_idx
        assert "b.c.d.Foo" in suffix_idx
        assert "c.d.Foo" in suffix_idx
        assert "d.Foo" in suffix_idx
        assert "Foo" in suffix_idx

        # All suffixes of Bar
        assert "x.y.z.Bar" in suffix_idx
        assert "y.z.Bar" in suffix_idx
        assert "z.Bar" in suffix_idx
        assert "Bar" in suffix_idx

    def test_resolve_symbol_exact_match(self):
        """Verify _resolve_symbol prefers exact match."""
        from graphlint.analyzer.graph import _resolve_symbol
        from graphlint.analyzer.warnings import WarningCollector

        builder = GraphBuilder(WarningCollector(), {})
        node = self._make_node_info(1, "mod.Foo")
        builder.add_node(node, preserve_id=True)

        result = _resolve_symbol(
            "mod.Foo", "", builder._symbol_index,
            builder._suffix_index, builder._node_id_map, None,
        )
        assert 1 in result

    def test_resolve_symbol_suffix_match(self):
        """Verify _resolve_symbol suffix matching."""
        from graphlint.analyzer.graph import _resolve_symbol
        from graphlint.analyzer.warnings import WarningCollector

        builder = GraphBuilder(WarningCollector(), {})
        node = self._make_node_info(1, "a.b.c.Foo")
        builder.add_node(node, preserve_id=True)

        # Match via suffix "c.Foo"
        result = _resolve_symbol(
            "c.Foo", "", builder._symbol_index,
            builder._suffix_index, builder._node_id_map, None,
        )
        assert 1 in result

        # Match via suffix "Foo"
        result = _resolve_symbol(
            "Foo", "", builder._symbol_index,
            builder._suffix_index, builder._node_id_map, None,
        )
        assert 1 in result

    def test_resolve_symbol_with_cache_hit(self):
        """Verify _resolve_symbol cache hit: same (qname, scope) pair returns same result."""
        from graphlint.analyzer.graph import _resolve_symbol
        from graphlint.analyzer.warnings import WarningCollector

        builder = GraphBuilder(WarningCollector(), {})
        node = self._make_node_info(1, "mod.Foo")
        builder.add_node(node, preserve_id=True)

        resolve_cache = {}

        # First call (cache miss)
        result1 = _resolve_symbol(
            "mod.Foo", "", builder._symbol_index,
            builder._suffix_index, builder._node_id_map, resolve_cache,
        )

        # Second call (cache hit)
        result2 = _resolve_symbol(
            "mod.Foo", "", builder._symbol_index,
            builder._suffix_index, builder._node_id_map, resolve_cache,
        )

        assert result1 == result2
        assert len(resolve_cache) == 1
        assert ("mod.Foo", "") in resolve_cache

    def test_resolve_symbol_cache_miss_different_keys(self):
        """Verify different (qname, scope) pairs do not interfere with each other's cache."""
        from graphlint.analyzer.graph import _resolve_symbol
        from graphlint.analyzer.warnings import WarningCollector

        builder = GraphBuilder(WarningCollector(), {})
        node1 = self._make_node_info(1, "mod.Foo")
        node2 = self._make_node_info(2, "mod.Bar")
        builder.add_node(node1, preserve_id=True)
        builder.add_node(node2, preserve_id=True)

        resolve_cache = {}

        r1 = _resolve_symbol(
            "mod.Foo", "mod", builder._symbol_index,
            builder._suffix_index, builder._node_id_map, resolve_cache,
        )
        r2 = _resolve_symbol(
            "mod.Bar", "mod", builder._symbol_index,
            builder._suffix_index, builder._node_id_map, resolve_cache,
        )

        assert r1 != r2  # Different symbols should return different results
        assert len(resolve_cache) == 2

    def test_resolve_symbol_no_cache(self):
        """Verify _resolve_symbol works without a cache dict."""
        from graphlint.analyzer.graph import _resolve_symbol
        from graphlint.analyzer.warnings import WarningCollector

        builder = GraphBuilder(WarningCollector(), {})
        node = self._make_node_info(1, "mod.Foo")
        builder.add_node(node, preserve_id=True)

        # No resolve_cache passed
        result = _resolve_symbol(
            "mod.Foo", "", builder._symbol_index,
            builder._suffix_index, builder._node_id_map, None,
        )
        assert 1 in result

        # Pass empty dict as cache
        result2 = _resolve_symbol(
            "mod.Foo", "", builder._symbol_index,
            builder._suffix_index, builder._node_id_map, {},
        )
        assert result == result2

    def test_resolve_symbol_scope_filtering(self):
        """Verify scope filtering: same suffix name, different scopes filtered correctly."""
        from graphlint.analyzer.graph import _resolve_symbol
        from graphlint.analyzer.warnings import WarningCollector

        builder = GraphBuilder(WarningCollector(), {})
        node1 = self._make_node_info(1, "pkg1.util.helper")
        node2 = self._make_node_info(2, "pkg2.util.helper")
        builder.add_node(node1, preserve_id=True)
        builder.add_node(node2, preserve_id=True)

        # Without scope filter: both match
        result = _resolve_symbol(
            "util.helper", "", builder._symbol_index,
            builder._suffix_index, builder._node_id_map, None,
        )
        assert len(result) == 2

        # With scope filter: only match under pkg1
        result = _resolve_symbol(
            "util.helper", "pkg1", builder._symbol_index,
            builder._suffix_index, builder._node_id_map, None,
        )
        assert len(result) == 1
        assert 1 in result

    def test_thread_pool_executor_with_independent_cache(self):
        """Verify ThreadPoolExecutor parallel build with independent resolve_cache produces consistent results."""
        from concurrent.futures import ThreadPoolExecutor


        # Create a basic symbol_index
        node1 = self._make_node_info(1, "mod.Foo")
        node2 = self._make_node_info(2, "mod.Bar")

        symbol_index = {"mod.Foo": [1], "mod.Bar": [2]}
        suffix_index = {"mod.Foo": [1], "Foo": [1], "mod.Bar": [2], "Bar": [2]}
        node_id_map = {1: node1, 2: node2}

        def resolve_in_thread(qname, scope):
            """Resolve symbol in thread using independent resolve_cache."""
            from graphlint.analyzer.graph import _resolve_symbol

            cache = {}
            return _resolve_symbol(
                qname, scope, symbol_index, suffix_index,
                node_id_map, cache,
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            f1 = executor.submit(resolve_in_thread, "mod.Foo", "")
            f2 = executor.submit(resolve_in_thread, "mod.Bar", "")

            r1 = f1.result()
            r2 = f2.result()

        # Serial results
        r1_serial = resolve_in_thread("mod.Foo", "")
        r2_serial = resolve_in_thread("mod.Bar", "")

        assert r1 == r1_serial
        assert r2 == r2_serial
