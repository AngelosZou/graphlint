# -*- coding: utf-8 -*-
"""Graph algorithms — connected components (BFS) and circular reference detection (Tarjan SCC)."""

from __future__ import annotations

from collections import deque
from typing import Optional

from graphlint.analyzer._types import ComponentInfo, EdgeInfo, EntryInfo, NodeInfo
from graphlint.analyzer.warnings import WarningInfo


_EMPTY_FROZENSET: frozenset[str] = frozenset()


def _resolve_entries(
    entries: list[EntryInfo],
    node_id_map: Optional[dict[int, NodeInfo]],
    file_id_map: Optional[dict[str, int]],
) -> tuple[set[int], set[int]]:
    """Resolve EntryInfo list → (entry_node_ids, noprop_node_ids)."""
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

    noprop_ids: set[int] = set()
    if file_entry_fids and node_id_map:
        for nid, ninfo in node_id_map.items():
            if ninfo.file_id in file_entry_fids:
                if ninfo.file_id in noprop_fids:
                    noprop_ids.add(nid)
                else:
                    entry_ids.add(nid)
    return entry_ids, noprop_ids


def compute_entry_reachability(
    edges: list[EdgeInfo],
    entries: list[EntryInfo],
    node_id_map: Optional[dict[int, NodeInfo]] = None,
    file_id_map: Optional[dict[str, int]] = None,
    call_graph: Optional[dict[int, list[int]]] = None,
    special_method_names: frozenset[str] = _EMPTY_FROZENSET,
    class_special_map: Optional[dict[int, list[int]]] = None,
    expanded_out: Optional[set[int]] = None,
) -> tuple[set[int], set[int]]:
    """Directed reachability analysis from entry points via CALL edges.
    """
    entry_ids, noprop_ids = _resolve_entries(entries, node_id_map, file_id_map)

    if not entry_ids and not noprop_ids:
        if expanded_out is not None:
            expanded_out.clear()
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

    # Track nodes whose CALL-graph downstream was fully explored by this BFS.
    # Excluded from the output: noprop (test-file) nodes — they do not
    # propagate reachability, so they are not safe pruning anchors.
    expanded: set[int] = set()

    # Precompute class -> [child special method IDs] mapping
    if class_special_map is None and node_id_map:
        class_special_map = {}
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

        expanded.add(current)

    # Test-file nodes are alive but do not propagate reachability.
    reachable.update(noprop_ids)

    # Expand: variables/fields whose parent is reachable are alive
    if node_id_map:
        for nid, ninfo in node_id_map.items():
            if nid not in reachable and ninfo.parent_node_id in reachable:
                if ninfo.node_type in ("variable", "field"):
                    reachable.add(nid)

    if expanded_out is not None:
        expanded_out.clear()
        expanded_out.update(expanded - noprop_ids)

    return reachable, noprop_ids


def _incremental_reachability(
    entries: list[EntryInfo],
    node_id_map: dict[int, NodeInfo],
    file_id_map: dict[str, int],
    call_graph: dict[int, list[int]],
    class_special_map: dict[int, list[int]],
    changed_node_ids: set[int],
    old_reachable: set[int],
) -> tuple[set[int], set[int]]:
    """Incremental reachability: propagate only from changed/entry nodes."""
    # entry resolution
    entry_ids, _noprop = _resolve_entries(entries, node_id_map, file_id_map)

    # reverse CALL graph (caller lookup for multi-source pruning)
    rev: dict[int, set[int]] = {}
    for src, targets in call_graph.items():
        for tgt in targets:
            rev.setdefault(tgt, set()).add(src)

    # optimistic candidate set
    reachable: set[int] = set(old_reachable)
    for eid in entry_ids:
        reachable.add(eid)

    if not reachable:
        return set(), _noprop

    # forward BFS
    queue: deque[int] = deque()
    scheduled: set[int] = set()
    for eid in entry_ids:
        if eid in changed_node_ids or eid not in old_reachable:
            queue.append(eid)
            scheduled.add(eid)
    for c in changed_node_ids:
        if c not in scheduled and c in old_reachable:
            queue.append(c)
            scheduled.add(c)

    while queue:
        cur = queue.popleft()
        if cur not in reachable:
            continue
        for target in call_graph.get(cur, []):
            if target not in reachable:
                reachable.add(target)
                queue.append(target)
                scheduled.add(target)
        # class-aware propagation
        if cur in class_special_map:
            for sm_nid in class_special_map[cur]:
                if sm_nid not in reachable:
                    reachable.add(sm_nid)
                    queue.append(sm_nid)
                    scheduled.add(sm_nid)

    # prune losses from changed nodes
    loss_q: deque[int] = deque()
    for c in changed_node_ids:
        if c not in old_reachable or c in entry_ids:
            continue
        callers = rev.get(c, set())
        if not any(clr in reachable for clr in callers):
            reachable.discard(c)
            loss_q.append(c)

    while loss_q:
        cur = loss_q.popleft()
        for target in call_graph.get(cur, []):
            if target not in reachable:
                continue
            if target in entry_ids:
                continue
            # multi-source pruning
            callers = rev.get(target, set())
            if any(clr in reachable and clr != cur for clr in callers):
                continue
            reachable.discard(target)
            loss_q.append(target)
        if cur in class_special_map:
            for sm_nid in class_special_map[cur]:
                if sm_nid in reachable:
                    reachable.discard(sm_nid)
                    loss_q.append(sm_nid)

    # expand variables / fields
    if node_id_map:
        for nid, ninfo in node_id_map.items():
            if nid not in reachable and ninfo.parent_node_id in reachable:
                if ninfo.node_type in ("variable", "field"):
                    reachable.add(nid)

    return reachable, _noprop


def _split_unreachable_by_call(
    unreachable: set[int],
    edges: list[EdgeInfo],
    comp_id_start: int,
    node_id_map: Optional[dict[int, NodeInfo]] = None,
    special_method_names: frozenset[str] = _EMPTY_FROZENSET,
    class_special_map: Optional[dict[int, list[int]]] = None,
) -> tuple[dict[int, int], list[ComponentInfo], int]:
    """Split unreachable nodes by CALL edges (undirected) into potential dead code components."""
    call_adj: dict[int, set[int]] = {nid: set() for nid in unreachable}
    for edge in edges:
        if edge.source_id in unreachable and edge.target_id in unreachable:
            call_adj.setdefault(edge.source_id, set()).add(edge.target_id)
            call_adj.setdefault(edge.target_id, set()).add(edge.source_id)

    # Include synthetic containment edges for special methods.
    if class_special_map:
        for parent, child_ids in class_special_map.items():
            if parent not in unreachable:
                continue
            for cid in child_ids:
                if cid in unreachable:
                    call_adj.setdefault(cid, set()).add(parent)
                    call_adj.setdefault(parent, set()).add(cid)
    elif node_id_map:
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
    expanded_out: Optional[set[int]] = None,
    changed_node_ids: Optional[set[int]] = None,
    old_reachable: Optional[set[int]] = None,
    reachable_out: Optional[set[int]] = None,
) -> tuple[dict[int, int], list[ComponentInfo]]:
    """Find all connected components."""
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

    # Precompute class->[special method child IDs] once (O(N)).
    class_special_map: dict[int, list[int]] = {}
    if node_id_map:
        for _nid, _ninfo in node_id_map.items():
            if _ninfo.name in special_method_names and _ninfo.parent_node_id:
                class_special_map.setdefault(_ninfo.parent_node_id, []).append(_nid)

    if old_reachable is not None and changed_node_ids is not None:
        reachable, noprop_ids = _incremental_reachability(
            entries, node_id_map, file_id_map,
            call_graph, class_special_map,
            changed_node_ids, old_reachable,
        )
    else:
        reachable, noprop_ids = compute_entry_reachability(
            edges, entries, node_id_map, file_id_map,
            call_graph=call_graph,
            special_method_names=special_method_names,
            class_special_map=class_special_map,
            expanded_out=expanded_out,
        )

    # Pre-compute globally reachable file IDs (excluding test-only nodes)
    global_reachable_fids: set[int] = set()
    if node_id_map:
        _non_noprop_reachable = reachable - noprop_ids if noprop_ids else reachable
        for _nid in _non_noprop_reachable:
            _ninfo = node_id_map.get(_nid)
            if _ninfo:
                global_reachable_fids.add(_ninfo.file_id)

    # Pre-compute node-0 connected node IDs (O(E) once)
    _zero_targets: set[int] = set()
    _zero_sources: set[int] = set()
    for _e in edges:
        if _e.edge_type in ("read", "call"):
            if _e.source_id == 0 and _e.target_id:
                _zero_targets.add(_e.target_id)
            elif _e.target_id == 0 and _e.source_id:
                _zero_sources.add(_e.source_id)

    # Pre-build entry indexes for O(1) per-component matching
    _nid_to_entries: dict[int, list[EntryInfo]] = {}
    _fid_to_entries: dict[int, list[EntryInfo]] = {}
    for entry in entries:
        if entry.node_id:
            _nid_to_entries.setdefault(entry.node_id, []).append(entry)
        elif file_id_map:
            fid = file_id_map.get(entry.file_path, 0)
            if fid:
                _fid_to_entries.setdefault(fid, []).append(entry)

    visited: set[int] = set()
    component_map: dict[int, int] = {}
    components: list[ComponentInfo] = []
    comp_id: int = 1

    for node in nodes:
        nid = node.id
        if nid in visited:
            continue

        # discover component nodes and initial reachable seeds
        queue: deque[int] = deque([nid])
        visited.add(nid)
        comp_nodes: set[int] = {nid}
        comp_reachable: set[int] = set()
        if nid in reachable:
            comp_reachable.add(nid)

        while queue:
            current = queue.popleft()
            for neighbor in adj.get(current, ()):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append(neighbor)
                    comp_nodes.add(neighbor)
                    if neighbor in reachable:
                        comp_reachable.add(neighbor)

        comp_entries = _match_entries(
            entries, comp_nodes, node_id_map, file_id_map,
            nid_to_entries=_nid_to_entries, fid_to_entries=_fid_to_entries,
        )
        has_entry = len(comp_entries) > 0
        comp_nodes.discard(0)
        comp_reachable.discard(0)
        comp_unreachable = comp_nodes - comp_reachable

        # BFS expansion from reachable seeds via undirected edges.
        if comp_unreachable:
            seed = comp_reachable
            if noprop_ids:
                seed = seed - noprop_ids
            q = deque(seed)
            while q:
                cur = q.popleft()
                if cur == 0:
                    continue
                for nb in adj.get(cur, ()):
                    if nb == 0 or nb in comp_reachable:
                        continue
                    if nb in comp_unreachable:
                        comp_reachable.add(nb)
                        comp_unreachable.discard(nb)
                        q.append(nb)
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
            for _nid in list(comp_unreachable):
                if _nid not in _zero_targets and _nid not in _zero_sources:
                    continue
                if _non_noprop:
                    comp_reachable.add(_nid)
                    comp_unreachable.discard(_nid)
                elif node_id_map:
                    _ni = node_id_map.get(_nid)
                    if _ni and _ni.file_id in global_reachable_fids:
                        comp_reachable.add(_nid)
                        comp_unreachable.discard(_nid)

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
                class_special_map=class_special_map,
            )
            component_map.update(sub_map)
            components.extend(sub_comps)

    # Post-process: merge dead components into live ones via inherit/decorate edges.
    comp_adj: dict[int, set[int]] = {}
    for e in edges:
        if e.edge_type not in ("inherit", "decorate"):
            continue
        cs = component_map.get(e.source_id)
        ct = component_map.get(e.target_id)
        if cs is not None and ct is not None and cs != ct:
            comp_adj.setdefault(cs, set()).add(ct)
            comp_adj.setdefault(ct, set()).add(cs)

    comp_by_id: dict[int, ComponentInfo] = {c.component_id: c for c in components}
    live_comp_ids: set[int] = {c.component_id for c in components if not c.is_dead_code}

    # each connected group containing a live
    # component merges all its dead members into the largest live one.
    comp_visited: set[int] = set()
    for live_cid in sorted(live_comp_ids):
        if live_cid in comp_visited:
            continue
        group: set[int] = {live_cid}
        comp_visited.add(live_cid)
        q_comp: deque[int] = deque([live_cid])
        while q_comp:
            cur_cid = q_comp.popleft()
            for nb_cid in comp_adj.get(cur_cid, set()):
                if nb_cid not in comp_visited:
                    comp_visited.add(nb_cid)
                    q_comp.append(nb_cid)
                    group.add(nb_cid)

        group_live = group & live_comp_ids
        group_dead = group - group_live
        if not group_dead:
            continue

        target_cid = max(group_live, key=lambda cid: len(comp_by_id[cid].node_ids))
        target_comp = comp_by_id[target_cid]
        for dead_cid in group_dead:
            dead_comp = comp_by_id.pop(dead_cid, None)
            if dead_comp is None:
                continue
            target_comp.node_ids.update(dead_comp.node_ids)
            for _nid in dead_comp.node_ids:
                component_map[_nid] = target_cid
            components.remove(dead_comp)

    if reachable_out is not None:
        live_ids = {c.component_id for c in components if not c.is_dead_code}
        reachable_out.clear()
        reachable_out.update(
            nid for nid, cid in component_map.items() if cid in live_ids
        )

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
    call_stack: list[tuple[int, int]] = []

    for start_v in digraph:
        if start_v in indices:
            continue
        call_stack.append((start_v, 0))
        while call_stack:
            v, child_idx = call_stack[-1]
            neighbors = digraph.get(v, [])
            if child_idx == 0:
                indices[v] = lowlink[v] = index
                index += 1
                stack.append(v)
                onstack.add(v)
            if child_idx < len(neighbors):
                w = neighbors[child_idx]
                call_stack[-1] = (v, child_idx + 1)
                if w not in indices:
                    call_stack.append((w, 0))
                elif w in onstack:
                    lowlink[v] = min(lowlink[v], indices[w])
            else:
                call_stack.pop()
                if call_stack:
                    parent_v, _ = call_stack[-1]
                    lowlink[parent_v] = min(lowlink[parent_v], lowlink[v])
                if lowlink[v] == indices[v]:
                    scc: list[int] = []
                    while True:
                        w = stack.pop()
                        onstack.discard(w)
                        scc.append(w)
                        if w == v:
                            break
                    sccs.append(scc)

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
    nid_to_entries: Optional[dict[int, list[EntryInfo]]] = None,
    fid_to_entries: Optional[dict[int, list[EntryInfo]]] = None,
) -> list[EntryInfo]:
    """Match entry points to connected components.
    """
    matched: list[EntryInfo] = []

    if nid_to_entries is not None and fid_to_entries is not None:
        comp_file_ids: set[int] = set()
        for nid in comp_nodes:
            for entry in nid_to_entries.get(nid, []):
                matched.append(entry)
            enode = node_id_map.get(nid)
            if enode:
                comp_file_ids.add(enode.file_id)
        for fid in comp_file_ids:
            for entry in fid_to_entries.get(fid, []):
                matched.append(entry)
        return matched

    if file_id_map is None:
        file_id_map = {}
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
