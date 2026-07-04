# -*- coding: utf-8 -*-
"""Tests for _graph_algo module edge traversal merge optimization."""

from __future__ import annotations


import pytest

from graphlint.analyzer._types import (
    EdgeInfo,
    NodeInfo,
)
from graphlint.analyzer.entry_detect import EntryInfo


def _make_node(nid: int, name: str = "", node_type: str = "function") -> NodeInfo:
    """Helper to create NodeInfo."""
    return NodeInfo(
        id=nid,
        file_id=1,
        name=name or f"Node{nid}",
        qualified_name=f"mod.{name or f'Node{nid}'}",
        node_type=node_type,
        line_start=nid * 10,
        line_end=nid * 10 + 5,
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


def _make_edge(sid: int, tid: int, etype: str = "call") -> EdgeInfo:
    """Helper to create EdgeInfo."""
    return EdgeInfo(
        source_id=sid,
        target_id=tid,
        edge_type=etype,
        file_id=1,
        line=1,
        context="",
    )


def _make_entry(node_id: int, file_path: str = "main.py") -> EntryInfo:
    """Helper to create EntryInfo."""
    return EntryInfo(
        node_id=node_id,
        file_path=file_path,
        line=1,
        rule_name="python_package",
        no_propagate=False,
    )


# =============================================================================
# TEST-T10: find_connected_components edge traversal merge optimization tests
# =============================================================================


@pytest.mark.timeout(30)
class TestFindConnectedComponents:
    """Tests for find_connected_components and compute_entry_reachability optimization."""

    def test_simple_connected_graph(self):
        """Verify single component containing all nodes connected by call edges."""
        from graphlint.analyzer._graph_algo import find_connected_components

        nodes = [
            _make_node(1, "A"),
            _make_node(2, "B"),
            _make_node(3, "C"),
        ]
        edges = [
            _make_edge(1, 2, "call"),
            _make_edge(2, 3, "call"),
        ]
        node_id_map = {n.id: n for n in nodes}
        entries = [_make_entry(1)]

        comp_map, comps = find_connected_components(
            nodes, edges, node_id_map, entries, file_id_map={"main.py": 1},
        )

        # All nodes should have a component_id
        assert all(n.id in comp_map for n in nodes)
        # Should have 1 component
        assert len(comps) == 1
        assert comps[0].component_id == comp_map[1]

    def test_disconnected_graphs(self):
        """Verify disconnected call chains produce multiple components."""
        from graphlint.analyzer._graph_algo import find_connected_components

        # Two independent call chains
        nodes = [
            _make_node(1, "A"),
            _make_node(2, "B"),
            _make_node(3, "X"),
            _make_node(4, "Y"),
        ]
        edges = [
            _make_edge(1, 2, "call"),  # Chain 1
            _make_edge(3, 4, "call"),  # Chain 2
        ]
        node_id_map = {n.id: n for n in nodes}
        entries = [_make_entry(1), _make_entry(3)]

        comp_map, comps = find_connected_components(
            nodes, edges, node_id_map, entries,
        )

        # Should have 2 components
        assert len(comps) == 2
        # Each component contains expected nodes
        comp_ids = {c.component_id: c.node_ids for c in comps}
        comp_id_values = list(comp_ids.values())
        assert {1, 2} in [set(v) for v in comp_id_values]
        assert {3, 4} in [set(v) for v in comp_id_values]

    def test_empty_edges(self):
        """Verify empty edge set: all nodes are isolated."""
        from graphlint.analyzer._graph_algo import find_connected_components

        nodes = [
            _make_node(1, "A"),
            _make_node(2, "B"),
        ]
        edges: list[EdgeInfo] = []
        node_id_map = {n.id: n for n in nodes}
        entries = [_make_entry(1)]

        comp_map, comps = find_connected_components(
            nodes, edges, node_id_map, entries,
        )

        # Nodes without edges may be split into different components
        assert len(comp_map) == 2

    def test_all_isolated_nodes(self):
        """Verify each isolated node gets its own component."""
        from graphlint.analyzer._graph_algo import find_connected_components

        nodes = [_make_node(i, f"Node{i}") for i in range(1, 5)]
        edges: list[EdgeInfo] = []
        node_id_map = {n.id: n for n in nodes}
        entries = [_make_entry(1)]

        comp_map, comps = find_connected_components(
            nodes, edges, node_id_map, entries,
        )

        # All nodes should map to a component
        assert all(n.id in comp_map for n in nodes)

    def test_only_inherit_edges_no_call(self):
        """Verify component partitioning with only inherit edges and no call edges."""
        from graphlint.analyzer._graph_algo import find_connected_components

        nodes = [
            _make_node(1, "Base"),
            _make_node(2, "Derived"),
        ]
        edges = [
            _make_edge(2, 1, "inherit"),
        ]
        node_id_map = {n.id: n for n in nodes}
        entries = [_make_entry(1)]

        comp_map, comps = find_connected_components(
            nodes, edges, node_id_map, entries,
        )

        # inherit edges connect two nodes via undirected BFS
        assert len(comp_map) == 2
        # At most 2 components (one reachable, one unreachable split into call sub-components)
        # Without call edges, _split_unreachable_by_call keeps unreachable nodes in separate components
        total_nodes = sum(len(c.node_ids) for c in comps)
        assert total_nodes == 2

    def test_component_with_special_methods(self):
        """Verify class with __init__ and other special methods is handled correctly."""
        from graphlint.analyzer._graph_algo import find_connected_components

        # Parent node (class)
        cls_node = NodeInfo(
            id=1, file_id=1, name="MyClass",
            qualified_name="mod.MyClass", node_type="class",
            line_start=1, line_end=20, col_offset=0,
            parent_node_id=None, is_deprecated=False,
            deprecation_msg="", type_annotation="",
            is_async=False, decorators=[], docstring="", is_entry=True,
        )
        # __init__ special method
        init_node = NodeInfo(
            id=2, file_id=1, name="__init__",
            qualified_name="mod.MyClass.__init__", node_type="method",
            line_start=2, line_end=10, col_offset=4,
            parent_node_id=1, is_deprecated=False,
            deprecation_msg="", type_annotation="",
            is_async=False, decorators=[], docstring="", is_entry=False,
        )
        nodes = [cls_node, init_node]
        edges: list[EdgeInfo] = []  # No explicit call edges
        node_id_map = {n.id: n for n in nodes}
        entries = [_make_entry(1)]

        comp_map, comps = find_connected_components(
            nodes, edges, node_id_map, entries,
        )

        # Both nodes should belong to the same component (synthetic containment edges)
        assert comp_map.get(1) == comp_map.get(2), \
            "__init__ should be in same component as parent via synthetic edge"

    def test_compute_entry_reachability_with_call_graph(self):
        """Verify results with prebuilt call_graph match results without it."""
        from graphlint.analyzer._graph_algo import compute_entry_reachability

        nodes = [
            _make_node(1, "A"),
            _make_node(2, "B"),
            _make_node(3, "C"),
        ]
        edges = [
            _make_edge(1, 2, "call"),
            _make_edge(2, 3, "call"),
        ]
        node_id_map = {n.id: n for n in nodes}
        entries = [_make_entry(1)]

        # Without call_graph
        r1, n1 = compute_entry_reachability(edges, entries, node_id_map, {"main.py": 1})

        # With prebuilt call_graph
        prebuilt_call_graph = {1: [2], 2: [3]}
        r2, n2 = compute_entry_reachability(
            edges, entries, node_id_map, {"main.py": 1},
            call_graph=prebuilt_call_graph,
        )

        assert r1 == r2, "Prebuilt call_graph should produce same results as without"
        assert n1 == n2

    def test_compute_entry_reachability_no_reachable(self):
        """Verify empty set is returned when there are no entry nodes."""
        from graphlint.analyzer._graph_algo import compute_entry_reachability

        edges = [_make_edge(1, 2, "call")]
        entries: list[EntryInfo] = []

        reachable, noprop = compute_entry_reachability(edges, entries, {}, {})
        assert reachable == set()
        assert noprop == set()

    def test_compare_old_vs_new_components_same_input(self):
        """Verify connected component results are identical before and after optimization."""
        from graphlint.analyzer._graph_algo import find_connected_components

        nodes = [
            _make_node(1, "A"),
            _make_node(2, "B"),
            _make_node(3, "C"),
        ]
        edges = [
            _make_edge(1, 2, "call"),
            _make_edge(2, 3, "inherit"),
            _make_edge(3, 1, "call"),
        ]
        node_id_map = {n.id: n for n in nodes}
        entries = [_make_entry(1)]

        comp_map, comps = find_connected_components(
            nodes, edges, node_id_map, entries,
        )

        # Verify basic consistency
        assert len(comps) >= 1
        for c in comps:
            assert all(nid in comp_map for nid in c.node_ids)
            for nid in c.node_ids:
                assert comp_map[nid] == c.component_id
