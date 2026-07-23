# -*- coding: utf-8 -*-
"""Graph algorithms — connected components (BFS) and circular reference detection (Tarjan SCC)."""

from __future__ import annotations

from collections import deque
from typing import Optional

from graphlint.analyzer._types import ComponentInfo, EdgeInfo, EntryInfo, NodeInfo
from graphlint.analyzer.warnings import WarningInfo


_EMPTY_FROZENSET: frozenset[str] = frozenset()


def compute_entry_reachability(
    edges: list[EdgeInfo],
    entries: list[EntryInfo],
    node_id_map: Optional[dict[int, NodeInfo]] = None,
    file_id_map: Optional[dict[str, int]] = None,
    call_graph: Optional[dict[int, list[int]]] = None,
    special_method_names: frozenset[str] = _EMPTY_FROZENSET,
) -> tuple[set[int], set[int]]:
    """Directed reachability analysis from entry points via CALL edges.

    Returns (reachable_ids, noprop_ids) where noprop_ids are nodes whose
    CALL edges should not propagate reachability (test-file entries).
    """
    entry_ids: set[int] = set()
    file_entry_fids: set[int] = set()
    noprop_fids: set[int] = set()

    for e in entries:
        if e.node_id:
            entry_ids.add(e.node_id)
        elif file_id_map and e.file_path:
            fid = file_id_map.get(e.file_path, 0)
            if fid:
                file_entry_fids.add(fid)
                if e.no_propagate:
                    noprop_fids.add(fid)

    # File-level entry expands to all nodes in that file
    noprop_ids: set[int] = set()
    if file_entry_fids and node_id_map:
        for nid, ninfo in node_id_map.items():
            if ninfo.file_id in file_entry_fids:
                if ninfo.file_id in noprop_fids:
                    noprop_ids.add(nid)
                else:
                    entry_ids.add(nid)

    if not entry_ids and not noprop_ids:
        return set(), set()

    if call_graph is None:
        # Build call_graph by iterating edges
        call_graph = {}
        for edge in edges:
            if edge.edge_type == "call":
                call_graph.setdefault(edge.source_id, []).append(edge.target_id)
            elif edge.edge_type == "read" and node_id_map:
                tgt = node_id_map.get(edge.target_id)
                if tgt and tgt.node_type in ("function", "class", "method"):
                    call_graph.setdefault(edge.source_id, []).append(edge.target_id)

    reachable: set[int] = set(entry_ids)
    queue: deque[int] = deque(entry_ids)

    # Precompute class -> [child special method IDs] mapping
    class_special_map: dict[int, list[int]] = {}
    if node_id_map:
        for nid, ninfo in node_id_map.items():
            if ninfo.name in special_method_names and ninfo.parent_node_id:
                class_special_map.setdefault(ninfo.parent_node_id, []).append(nid)

    while queue:
        current = queue.popleft()
        for target in call_graph.get(current, []):
            if target not in reachable:
                reachable.add(target)
                queue.append(target)

        # Propagate class reachability to all special methods.
        if current in class_special_map:
            for sm_nid in class_special_map[current]:
                if sm_nid not in reachable:
                    reachable.add(sm_nid)
                    queue.append(sm_nid)

    # Test-file nodes are alive but do not propagate reachability.
    reachable.update(noprop_ids)

    # Expand: variables/fields whose parent is reachable are alive
    if node_id_map:
        for nid, ninfo in node_id_map.items():
            if nid not in reachable and ninfo.parent_node_id in reachable:
                if ninfo.node_type in ("variable", "field"):
                    reachable.add(nid)

    return reachable, noprop_ids


def _split_unreachable_by_call(
    unreachable: set[int],
    edges: list[EdgeInfo],
    comp_id_start: int,
    node_id_map: Optional[dict[int, NodeInfo]] = None,
    special_method_names: frozenset[str] = _EMPTY_FROZENSET,
) -> tuple[dict[int, int], list[ComponentInfo], int]:
    """Split unreachable nodes by CALL edges (undirected) into potential dead code components."""
    call_adj: dict[int, set[int]] = {nid: set() for nid in unreachable}
    for edge in edges:
        if edge.source_id in unreachable and edge.target_id in unreachable:
            call_adj.setdefault(edge.source_id, set()).add(edge.target_id)
            call_adj.setdefault(edge.target_id, set()).add(edge.source_id)

    # Include synthetic containment edges for special methods.
    if node_id_map:
        for nid, ninfo in node_id_map.items():
            if (
                ninfo.name in special_method_names
                and ninfo.parent_node_id
                and nid in unreachable
                and ninfo.parent_node_id in unreachable
            ):
                parent = ninfo.parent_node_id
                call_adj.setdefault(nid, set()).add(parent)
                call_adj.setdefault(parent, set()).add(nid)

    comp_map: dict[int, int] = {}
    comps: list[ComponentInfo] = []
    visited: set[int] = set()
    comp_id = comp_id_start

    for nid in unreachable:
        if nid in visited:
            continue
        group: set[int] = {nid}
        visited.add(nid)
        q: deque[int] = deque([nid])
        while q:
            cur = q.popleft()
            for nb in call_adj.get(cur, set()):
                if nb not in visited:
                    visited.add(nb)
                    q.append(nb)
                    group.add(nb)

        for m in group:
            comp_map[m] = comp_id
        comps.append(
            ComponentInfo(
                component_id=comp_id,
                node_ids=group,
                entry_info=[],
                is_dead_code=True,
                is_unreachable=True,
            )
        )
        comp_id += 1

    return comp_map, comps, comp_id


def find_connected_components(
    nodes: list[NodeInfo],
    edges: list[EdgeInfo],
    node_id_map: dict[int, NodeInfo],
    entries: list[EntryInfo],
    file_id_map: Optional[dict[str, int]] = None,
    public_api_names: frozenset[str] = _EMPTY_FROZENSET,
    special_method_names: frozenset[str] = _EMPTY_FROZENSET,
) -> tuple[dict[int, int], list[ComponentInfo]]:
    """Find all connected components via undirected BFS, split by CALL reachability."""
    adj: dict[int, set[int]] = {}
    for node in nodes:
        nid = node.id
        adj.setdefault(nid, set())

    for edge in edges:
        if edge.source_id == 0 or edge.target_id == 0:
            continue  # exclude module pseudo-node — avoids cross-file merging
        adj.setdefault(edge.source_id, set()).add(edge.target_id)
        adj.setdefault(edge.target_id, set()).add(edge.source_id)

    # Add synthetic containment edges for special method overloads.
    if node_id_map:
        for nid, ninfo in node_id_map.items():
            if ninfo.name in special_method_names and ninfo.parent_node_id:
                parent = ninfo.parent_node_id
                adj.setdefault(nid, set()).add(parent)
                adj.setdefault(parent, set()).add(nid)

    # Connect public API dunders to their file's first non-dunder node.
    if node_id_map:
        _fid_first: dict[int, int] = {}
        for _ninfo in node_id_map.values():
            if _ninfo.name not in public_api_names and _ninfo.file_id not in _fid_first:
                _fid_first[_ninfo.file_id] = _ninfo.id
        for _ninfo in node_id_map.values():
            if _ninfo.name in public_api_names and _ninfo.node_type in ("variable", "field"):
                _first = _fid_first.get(_ninfo.file_id)
                if _first is not None:
                    adj.setdefault(_ninfo.id, set()).add(_first)
                    adj.setdefault(_first, set()).add(_ninfo.id)

    # Pre-build call_graph once to avoid repeated traversal inside compute_entry_reachability
    call_graph: dict[int, list[int]] = {}
    for edge in edges:
        if edge.edge_type == "call":
            call_graph.setdefault(edge.source_id, []).append(edge.target_id)
        elif edge.edge_type == "read" and node_id_map:
            tgt = node_id_map.get(edge.target_id)
            if tgt and tgt.node_type in ("function", "class", "method"):
                call_graph.setdefault(edge.source_id, []).append(edge.target_id)

    reachable, noprop_ids = compute_entry_reachability(
        edges, entries, node_id_map, file_id_map,
        call_graph=call_graph,
        special_method_names=special_method_names,
    )

    # Pre-compute globally reachable file IDs (excluding test-only nodes)
    # so that isolated module-level variables in reachable files can be
    # pulled into their file's component via node-0 expansion.
    global_reachable_fids: set[int] = set()
    if node_id_map:
        _non_noprop_reachable = reachable - noprop_ids if noprop_ids else reachable
        for _nid in _non_noprop_reachable:
            _ninfo = node_id_map.get(_nid)
            if _ninfo:
                global_reachable_fids.add(_ninfo.file_id)

    visited: set[int] = set()
    component_map: dict[int, int] = {}
    components: list[ComponentInfo] = []
    comp_id: int = 1

    for node in nodes:
        nid = node.id
        if nid in visited:
            continue

        queue: deque[int] = deque([nid])
        visited.add(nid)
        comp_nodes: set[int] = {nid}

        while queue:
            current = queue.popleft()
            for neighbor in adj.get(current, set()):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)
                    comp_nodes.add(neighbor)

        comp_entries = _match_entries(entries, comp_nodes, node_id_map, file_id_map)
        has_entry = len(comp_entries) > 0
        comp_nodes.discard(0)  # Exclude module root pseudo-node
        comp_reachable = {nid for nid in comp_nodes if nid in reachable}
        comp_unreachable = comp_nodes - comp_reachable

        # BFS expansion from reachable seed set via undirected edges.
        # Node 0 (module pseudo-node): only expand via read/call edges.
        seed = comp_reachable
        if noprop_ids:
            seed = seed - noprop_ids
        q = deque(seed)
        class_special_map: dict[int, list[int]] = {}
        if node_id_map:
            for _nid, _ninfo in node_id_map.items():
                if _ninfo.name in special_method_names and _ninfo.parent_node_id:
                    class_special_map.setdefault(_ninfo.parent_node_id, []).append(_nid)
        while q:
            cur = q.popleft()
            if cur == 0:
                continue
            for nid in adj.get(cur, set()):
                if nid == 0 or nid in comp_reachable:
                    continue
                if nid in comp_unreachable:
                    comp_reachable.add(nid)
                    comp_unreachable.discard(nid)
                    q.append(nid)
            if cur in class_special_map:
                for sm_nid in class_special_map[cur]:
                    if sm_nid in comp_unreachable:
                        comp_reachable.add(sm_nid)
                        comp_unreachable.discard(sm_nid)
                        q.append(sm_nid)

        # Expand via module pseudo-node (id=0) edges for components
        # with non-test reachable nodes or isolated vars in reachable
        # files.  Skip test-only (noprop) components.
        _non_noprop = (
            comp_reachable - noprop_ids
            if noprop_ids and comp_reachable
            else comp_reachable
        )
        _expand_via_module = bool(_non_noprop) or not comp_reachable
        if _expand_via_module:
            for e in edges:
                if e.source_id == 0 and e.target_id in comp_unreachable:
                    if e.edge_type in ("read", "call"):
                        tgt_info = node_id_map.get(e.target_id, NodeInfo()) if node_id_map else None
                        if _non_noprop or (tgt_info and tgt_info.file_id in global_reachable_fids):
                            comp_reachable.add(e.target_id)
                            comp_unreachable.discard(e.target_id)
                elif e.target_id == 0 and e.source_id in comp_unreachable:
                    if e.edge_type in ("read", "call"):
                        src_info = node_id_map.get(e.source_id, NodeInfo()) if node_id_map else None
                        if _non_noprop or (src_info and src_info.file_id in global_reachable_fids):
                            comp_reachable.add(e.source_id)
                            comp_unreachable.discard(e.source_id)

        # Merge public API dunders into reachable components from the same file.
        if comp_reachable and comp_unreachable and node_id_map:
            reachable_fids: set[int] = set()
            for _nid in comp_reachable:
                _info = node_id_map.get(_nid)
                if _info:
                    reachable_fids.add(_info.file_id)
            for _nid in list(comp_unreachable):
                _info = node_id_map.get(_nid)
                if _info and _info.file_id in reachable_fids and _info.name in public_api_names:
                    comp_reachable.add(_nid)
                    comp_unreachable.discard(_nid)

        if comp_reachable:
            for nid in comp_reachable:
                component_map[nid] = comp_id
            components.append(
                ComponentInfo(
                    component_id=comp_id,
                    node_ids=comp_reachable,
                    entry_info=comp_entries,
                    is_dead_code=not has_entry,
                )
            )
            comp_id += 1

        if comp_unreachable:
            sub_map, sub_comps, comp_id = _split_unreachable_by_call(
                comp_unreachable,
                edges,
                comp_id,
                node_id_map,
                special_method_names=special_method_names,
            )
            component_map.update(sub_map)
            components.extend(sub_comps)

    # Post-process: merge dead code sub-components into live components.
    x_edges: dict[int, set[int]] = {}
    for e in edges:
        if e.edge_type not in ("inherit", "decorate"):
            continue
        cs = component_map.get(e.source_id)
        ct = component_map.get(e.target_id)
        if cs is not None and ct is not None and cs != ct:
            x_edges.setdefault(cs, set()).add(ct)
            x_edges.setdefault(ct, set()).add(cs)

    comp_by_id: dict[int, ComponentInfo] = {c.component_id: c for c in components}

    changed = True
    while changed:
        changed = False
        for comp in list(components):
            if not comp.is_dead_code:
                continue
            neighbors = x_edges.get(comp.component_id, set())
            if not neighbors:
                continue
            # Find all adjacent live components
            live_nbrs = []
            for nbr in neighbors:
                nbr_comp = comp_by_id.get(nbr)
                if nbr_comp and not nbr_comp.is_dead_code:
                    live_nbrs.append(nbr_comp)
            if not live_nbrs:
                continue
            target = max(live_nbrs, key=lambda c: len(c.node_ids))
            target.node_ids.update(comp.node_ids)
            for nid in list(comp.node_ids):
                component_map[nid] = target.component_id
            for other in list(neighbors):
                if other == target.component_id:
                    continue
                x_edges.setdefault(other, set()).discard(comp.component_id)
                x_edges.setdefault(other, set()).add(target.component_id)
                x_edges.setdefault(target.component_id, set()).add(other)
            x_edges.pop(comp.component_id, None)
            comp_by_id.pop(comp.component_id, None)
            components.remove(comp)
            changed = True
            break

    return component_map, components


def _build_warnings(
    sccs: list[list[int]], node_id_map: dict[int, NodeInfo]
) -> list[WarningInfo]:
    """Generate circular_ref warnings from SCC list."""
    warnings: list[WarningInfo] = []
    for scc in sccs:
        if len(scc) > 1:
            names = [node_id_map.get(nid, NodeInfo()).name for nid in scc]
            msg = f"Circular dependency detected: {' → '.join(names)}"
            warnings.append(
                WarningInfo(
                    warn_type="circular_ref",
                    severity="warning",
                    message=msg,
                    node_id=scc[0],
                    file_path=getattr(node_id_map.get(scc[0]), "file_path", ""),
                    line=getattr(node_id_map.get(scc[0]), "line_start", 0),
                )
            )
    return warnings


def detect_circular_refs(
    nodes: list[NodeInfo],
    edges: list[EdgeInfo],
    node_id_map: dict[int, NodeInfo],
) -> list[WarningInfo]:
    """Detect circular references using Tarjan SCC algorithm on CALL/INHERIT edges."""
    digraph: dict[int, list[int]] = {}
    for node in nodes:
        digraph[_get_node_id(nodes, node)] = []
    for edge in edges:
        if edge.edge_type in ("call", "inherit"):
            digraph.setdefault(edge.source_id, []).append(edge.target_id)

    indices: dict[int, int] = {}
    lowlink: dict[int, int] = {}
    onstack: set[int] = set()
    stack: list[int] = []
    sccs: list[list[int]] = []
    index = 0

    def strongconnect(v: int) -> None:
        nonlocal index
        indices[v] = lowlink[v] = index
        index += 1
        stack.append(v)
        onstack.add(v)
        for w in digraph.get(v, []):
            if w not in indices:
                strongconnect(w)
                lowlink[v] = min(lowlink[v], lowlink[w])
            elif w in onstack:
                lowlink[v] = min(lowlink[v], indices[w])
        if lowlink[v] == indices[v]:
            scc: list[int] = []
            while True:
                w = stack.pop()
                onstack.discard(w)
                scc.append(w)
                if w == v:
                    break
            sccs.append(scc)

    for v in digraph:
        if v not in indices:
            strongconnect(v)

    return _build_warnings(sccs, node_id_map)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_node_id(nodes: list[NodeInfo], node: NodeInfo) -> int:
    """Find a node's ID by matching qualified_name, file_id, and line_start."""
    for n in nodes:
        if (
            n.qualified_name == node.qualified_name
            and n.file_id == node.file_id
            and n.line_start == node.line_start
        ):
            return n.id
    return 0


def _match_entries(
    entries: list[EntryInfo],
    comp_nodes: set[int],
    node_id_map: dict[int, NodeInfo],
    file_id_map: Optional[dict[str, int]] = None,
) -> list[EntryInfo]:
    """Match entry points to connected components."""
    if file_id_map is None:
        file_id_map = {}
    matched: list[EntryInfo] = []
    for entry in entries:
        if entry.node_id in comp_nodes:
            matched.append(entry)
        elif entry.node_id == 0:
            entry_fid = file_id_map.get(entry.file_path, 0)
            if entry_fid == 0:
                continue
            for nid in comp_nodes:
                enode = node_id_map.get(nid)
                if enode and enode.file_id == entry_fid:
                    matched.append(entry)
                    break
    return matched
