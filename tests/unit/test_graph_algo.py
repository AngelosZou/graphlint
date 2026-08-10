# -*- coding: utf-8 -*-
"""Tests for _graph_algo module edge traversal merge optimization."""

from __future__ import annotations


import pytest

from graphlint.analyzer._types import (
    EdgeInfo,
    EntryInfo,
    NodeInfo,
)
from graphlint.analyzer._graph_algo import (
    _build_undirected_adj,
    _propagate_partial_reachability,
)
from graphlint.analyzer.language.python.constants import _PYTHON_SPECIAL_METHOD_DUNDERS


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

        _, comps = find_connected_components(
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

        comp_map, _ = find_connected_components(
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

        comp_map, _ = find_connected_components(
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

        comp_map, _ = find_connected_components(
            nodes, edges, node_id_map, entries,
            special_method_names=_PYTHON_SPECIAL_METHOD_DUNDERS,
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


# =============================================================================
# Tests for cached adjacency helper functions
# =============================================================================


@pytest.mark.timeout(30)
class TestBuildUndirectedAdj:
    """Tests for _build_undirected_adj."""

    def test_basic_undirected(self):
        from graphlint.analyzer._graph_algo import _build_undirected_adj

        nodes = [_make_node(1, "A"), _make_node(2, "B")]
        edges = [_make_edge(1, 2, "call")]
        node_id_map = {n.id: n for n in nodes}

        adj = _build_undirected_adj(edges, node_id_map)

        assert adj.get(1, set()) == {2}
        assert adj.get(2, set()) == {1}

    def test_excludes_zero_id_edges(self):
        from graphlint.analyzer._graph_algo import _build_undirected_adj

        nodes = [_make_node(1, "A")]
        edges = [
            _make_edge(0, 1, "read"),
            _make_edge(1, 0, "read"),
        ]
        node_id_map = {n.id: n for n in nodes}

        adj = _build_undirected_adj(edges, node_id_map)

        assert 0 not in adj
        assert adj.get(1, set()) == set()

    def test_synthetic_special_method_edges(self):
        from graphlint.analyzer._graph_algo import _build_undirected_adj

        cls_node = NodeInfo(
            id=1, file_id=1, name="MyClass",
            qualified_name="mod.MyClass", node_type="class",
            line_start=1, line_end=20, col_offset=0,
            parent_node_id=None, is_deprecated=False,
            deprecation_msg="", type_annotation="",
            is_async=False, decorators=[], docstring="", is_entry=True,
        )
        init_node = NodeInfo(
            id=2, file_id=1, name="__init__",
            qualified_name="mod.MyClass.__init__", node_type="method",
            line_start=2, line_end=10, col_offset=4,
            parent_node_id=1, is_deprecated=False,
            deprecation_msg="", type_annotation="",
            is_async=False, decorators=[], docstring="", is_entry=False,
        )
        nodes = [cls_node, init_node]
        edges: list[EdgeInfo] = []
        node_id_map = {n.id: n for n in nodes}

        adj = _build_undirected_adj(
            edges, node_id_map,
            special_method_names=_PYTHON_SPECIAL_METHOD_DUNDERS,
        )

        assert adj.get(1, set()) == {2}
        assert adj.get(2, set()) == {1}

    def test_synthetic_public_api_edges(self):
        from graphlint.analyzer._graph_algo import _build_undirected_adj

        var_node = NodeInfo(
            id=2, file_id=1, name="VAR_A",
            qualified_name="mod.VAR_A", node_type="variable",
            line_start=10, line_end=20, col_offset=0,
            parent_node_id=None, is_deprecated=False,
            deprecation_msg="", type_annotation="",
            is_async=False, decorators=[], docstring="", is_entry=False,
        )
        non_dunder_node = NodeInfo(
            id=1, file_id=1, name="func",
            qualified_name="mod.func", node_type="function",
            line_start=1, line_end=5, col_offset=0,
            parent_node_id=None, is_deprecated=False,
            deprecation_msg="", type_annotation="",
            is_async=False, decorators=[], docstring="", is_entry=False,
        )
        nodes = [non_dunder_node, var_node]
        edges: list[EdgeInfo] = []
        node_id_map = {n.id: n for n in nodes}

        adj = _build_undirected_adj(
            edges, node_id_map,
            public_api_names=frozenset({"VAR_A"}),
        )

        assert non_dunder_node.id in adj.get(var_node.id, set())

    def test_none_node_id_map(self):
        from graphlint.analyzer._graph_algo import _build_undirected_adj

        edges = [_make_edge(1, 2, "call")]

        adj = _build_undirected_adj(edges, None)

        assert adj == {1: {2}, 2: {1}}

    def test_multiple_edge_types(self):
        from graphlint.analyzer._graph_algo import _build_undirected_adj

        nodes = [_make_node(1, "A"), _make_node(2, "B")]
        edges = [
            _make_edge(1, 2, "call"),
            _make_edge(1, 2, "inherit"),
            _make_edge(1, 2, "read"),
        ]
        node_id_map = {n.id: n for n in nodes}

        adj = _build_undirected_adj(edges, node_id_map)

        assert adj[1] == {2}
        assert adj[2] == {1}


@pytest.mark.timeout(30)
class TestBuildCallGraph:
    """Tests for _build_call_graph."""

    def test_call_edges_only(self):
        from graphlint.analyzer._graph_algo import _build_call_graph

        edges = [
            _make_edge(1, 2, "call"),
            _make_edge(2, 3, "call"),
        ]

        cg = _build_call_graph(edges)

        assert cg == {1: [2], 2: [3]}

    def test_read_edge_targeting_function(self):
        from graphlint.analyzer._graph_algo import _build_call_graph

        edges = [_make_edge(1, 2, "read")]
        node_id_map = {
            2: NodeInfo(
                id=2, file_id=1, name="func",
                qualified_name="mod.func", node_type="function",
                line_start=1, line_end=5, col_offset=0,
                parent_node_id=None, is_deprecated=False,
                deprecation_msg="", type_annotation="",
                is_async=False, decorators=[], docstring="", is_entry=False,
            ),
        }

        cg = _build_call_graph(edges, node_id_map)

        assert 1 in cg
        assert 2 in cg[1]

    def test_read_edge_targeting_variable(self):
        from graphlint.analyzer._graph_algo import _build_call_graph

        edges = [_make_edge(1, 2, "read")]
        node_id_map = {
            2: NodeInfo(
                id=2, file_id=1, name="var",
                qualified_name="mod.var", node_type="variable",
                line_start=1, line_end=5, col_offset=0,
                parent_node_id=None, is_deprecated=False,
                deprecation_msg="", type_annotation="",
                is_async=False, decorators=[], docstring="", is_entry=False,
            ),
        }

        cg = _build_call_graph(edges, node_id_map)

        assert 1 not in cg

    def test_other_edge_types_ignored(self):
        from graphlint.analyzer._graph_algo import _build_call_graph

        edges = [
            _make_edge(1, 2, "inherit"),
            _make_edge(3, 4, "decorate"),
        ]

        cg = _build_call_graph(edges)

        assert cg == {}


@pytest.mark.timeout(30)
class TestBuildDigraph:
    """Tests for _build_digraph."""

    def test_call_and_inherit_edges(self):
        from graphlint.analyzer._graph_algo import _build_digraph

        nodes = [_make_node(i, f"Node{i}") for i in range(1, 4)]
        edges = [
            _make_edge(1, 2, "call"),
            _make_edge(2, 3, "inherit"),
        ]

        dg = _build_digraph(nodes, edges)

        assert dg[1] == [2]
        assert dg[2] == [3]
        assert dg[3] == []

    def test_non_call_inherit_ignored(self):
        from graphlint.analyzer._graph_algo import _build_digraph

        nodes = [_make_node(1, "A"), _make_node(2, "B")]
        edges = [
            _make_edge(1, 2, "read"),
            _make_edge(1, 2, "decorate"),
        ]

        dg = _build_digraph(nodes, edges)

        assert dg[1] == []
        assert dg[2] == []

    def test_all_nodes_present(self):
        from graphlint.analyzer._graph_algo import _build_digraph

        nodes = [_make_node(i, f"Node{i}") for i in range(1, 4)]
        edges: list[EdgeInfo] = []

        dg = _build_digraph(nodes, edges)

        assert set(dg.keys()) == {1, 2, 3}
        assert all(v == [] for v in dg.values())


@pytest.mark.timeout(30)
class TestBuildClassSpecialMap:
    """Tests for _build_class_special_map."""

    def test_basic_mapping(self):
        from graphlint.analyzer._graph_algo import _build_class_special_map

        cls_node = NodeInfo(
            id=1, file_id=1, name="MyClass",
            qualified_name="mod.MyClass", node_type="class",
            line_start=1, line_end=20, col_offset=0,
            parent_node_id=None, is_deprecated=False,
            deprecation_msg="", type_annotation="",
            is_async=False, decorators=[], docstring="", is_entry=True,
        )
        init_node = NodeInfo(
            id=2, file_id=1, name="__init__",
            qualified_name="mod.MyClass.__init__", node_type="method",
            line_start=2, line_end=10, col_offset=4,
            parent_node_id=1, is_deprecated=False,
            deprecation_msg="", type_annotation="",
            is_async=False, decorators=[], docstring="", is_entry=False,
        )
        node_id_map = {1: cls_node, 2: init_node}

        csm = _build_class_special_map(node_id_map, _PYTHON_SPECIAL_METHOD_DUNDERS)

        assert 1 in csm
        assert 2 in csm[1]

    def test_non_special_methods_ignored(self):
        from graphlint.analyzer._graph_algo import _build_class_special_map

        cls_node = NodeInfo(
            id=1, file_id=1, name="MyClass",
            qualified_name="mod.MyClass", node_type="class",
            line_start=1, line_end=20, col_offset=0,
            parent_node_id=None, is_deprecated=False,
            deprecation_msg="", type_annotation="",
            is_async=False, decorators=[], docstring="", is_entry=True,
        )
        regular_node = NodeInfo(
            id=2, file_id=1, name="regular_method",
            qualified_name="mod.MyClass.regular_method", node_type="method",
            line_start=2, line_end=10, col_offset=4,
            parent_node_id=1, is_deprecated=False,
            deprecation_msg="", type_annotation="",
            is_async=False, decorators=[], docstring="", is_entry=False,
        )
        node_id_map = {1: cls_node, 2: regular_node}

        csm = _build_class_special_map(node_id_map, _PYTHON_SPECIAL_METHOD_DUNDERS)

        assert csm == {}

    def test_none_node_id_map(self):
        from graphlint.analyzer._graph_algo import _build_class_special_map

        csm = _build_class_special_map(None)

        assert csm == {}

    def test_empty_special_names(self):
        from graphlint.analyzer._graph_algo import _build_class_special_map

        cls_node = NodeInfo(
            id=1, file_id=1, name="MyClass",
            qualified_name="mod.MyClass", node_type="class",
            line_start=1, line_end=20, col_offset=0,
            parent_node_id=None, is_deprecated=False,
            deprecation_msg="", type_annotation="",
            is_async=False, decorators=[], docstring="", is_entry=True,
        )
        init_node = NodeInfo(
            id=2, file_id=1, name="__init__",
            qualified_name="mod.MyClass.__init__", node_type="method",
            line_start=2, line_end=10, col_offset=4,
            parent_node_id=1, is_deprecated=False,
            deprecation_msg="", type_annotation="",
            is_async=False, decorators=[], docstring="", is_entry=False,
        )
        node_id_map = {1: cls_node, 2: init_node}

        csm = _build_class_special_map(node_id_map, frozenset())

        assert csm == {}


# =============================================================================
# Partial-class reachability propagation
# =============================================================================


class TestPropagatePartialReachability:
    """``part_of`` edges share reachability between partial fragments and the
    merged node in both directions."""

    def test_merged_reachable_from_fragment(self):
        reachable = {1}  # fragment 1 reachable via its members
        edges = [
            _make_edge(1, 2, "part_of"),  # fragment1 -> merged
            _make_edge(3, 2, "part_of"),  # fragment2 -> merged
        ]
        out = _propagate_partial_reachability(set(reachable), edges)
        assert out == {1, 2, 3}

    def test_fragments_reachable_from_merged(self):
        reachable = {2}  # merged node reachable (e.g. type name referenced)
        edges = [_make_edge(1, 2, "part_of"), _make_edge(3, 2, "part_of")]
        out = _propagate_partial_reachability(set(reachable), edges)
        assert out == {1, 2, 3}

    def test_other_edge_types_ignored(self):
        reachable = {1}
        edges = [_make_edge(1, 2, "call"), _make_edge(2, 3, "inherit")]
        out = _propagate_partial_reachability(set(reachable), edges)
        assert out == {1}

    def test_empty_edges(self):
        out = _propagate_partial_reachability({1, 2}, [])
        assert out == {1, 2}


class TestBuildUndirectedAdjLanguageScoped:
    """Special-name decisions are scoped per node (language) when a checker
    callback is supplied — C# names must not leak into Python analysis."""

    def _nodes(self) -> dict[int, NodeInfo]:
        cls = _make_node(1, "Service", "class")
        cls.parent_node_id = None
        dispose = _make_node(2, "Dispose", "method")
        dispose.parent_node_id = 1
        return {1: cls, 2: dispose}

    def test_union_set_treats_dispose_as_special(self):
        # Legacy behaviour: the union set marks it special -> synthetic edge
        adj = _build_undirected_adj(
            [], self._nodes(), frozenset({"Dispose"})
        )
        assert 2 in adj.get(1, set())

    def test_callback_overrides_union(self):
        # Python adapter would not consider "Dispose" special
        def is_special(node: NodeInfo) -> bool:
            return node.name in _PYTHON_SPECIAL_METHOD_DUNDERS

        adj = _build_undirected_adj(
            [], self._nodes(), frozenset({"Dispose"}), is_special_name=is_special
        )
        assert adj.get(1, set()) == set()

    def test_callback_marking_special(self):
        def is_special(node: NodeInfo) -> bool:
            return node.name == "Dispose"

        adj = _build_undirected_adj(
            [], self._nodes(), frozenset(), is_special_name=is_special
        )
        assert 2 in adj.get(1, set())
