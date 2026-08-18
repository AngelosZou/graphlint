# -*- coding: utf-8 -*-
"""Dependency graph builder — builds directed/undirected edges, detects circular references and connected components."""

from __future__ import annotations

import os
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Any, Callable, Optional

from graphlint.analyzer._graph_algo import (
    _build_call_graph,
    _build_class_special_map,
    _build_digraph,
    _build_undirected_adj,
    detect_circular_refs,
    find_connected_components,
)
from graphlint.analyzer._types import (
    ComponentInfo,
    EdgeInfo,
    EntryInfo,
    GraphBuildResult,
    NodeInfo,
    ParseResult,
)
from graphlint.analyzer.language.base import LanguageAdapter
from graphlint.analyzer.language.registry import LanguageRegistry
from graphlint.analyzer.warnings import (
    WarningCollector,
    detect_write_only_nodes,
)


# ---------------------------------------------------------------------------
# Symbol resolution (used by edge building and reference resolution)
# ---------------------------------------------------------------------------


def _resolve_symbol(
    qname: str,
    scope: str,
    symbol_index: dict[str, list[int]],
    suffix_index: dict[str, list[int]],
    node_id_map: dict[int, NodeInfo],
    resolve_cache: Optional[dict] = None,
    scope_suffix_index: Optional[dict[tuple[str, str], list[int]]] = None,
    class_scope: str = "",
    fid: int = 0,
    file_suffix_index: Optional[dict[tuple[int, str], list[int]]] = None,
) -> list[int]:
    """Resolve a symbol by exact qualified-name match, then suffix fallback.

    Args:
        qname: The symbol simple name to resolve (e.g. ``"field_name"``).
        scope: Qualified name of the calling scope (e.g. ``"pkg.mod.MyClass.method"``).
        symbol_index: Exact qualified-name lookup table.
        suffix_index: Suffix-based lookup for partial matches.
        node_id_map: Global node ID to NodeInfo mapping.
        resolve_cache: Optional cache keyed by ``(qname, scope)``.
        scope_suffix_index: Optional ``(scope, simple_name)`` lookup table.
        class_scope: Fallback scope for class-level field resolution.
        fid: Optional source file ID. When given together with
            ``file_suffix_index``, C translation-unit scope applies:
            same-file symbols win over cross-file matches. Cross-file
            ``static`` filtering is applied by the caller (it needs the
            include closure — a ``static`` in an included header is per-TU
            and stays reachable).

    Returns:
        List of node IDs matching the symbol. Empty list when no match is found.
    """
    cache_key = (qname, scope)
    if resolve_cache is not None and cache_key in resolve_cache:
        cached = resolve_cache[cache_key]
        return list(cached) if cached else []

    if qname in symbol_index:
        result = list(symbol_index[qname])
        if resolve_cache is not None:
            resolve_cache[cache_key] = result if result else []
        return result

    # Normalise Rust "::" → "." for unified suffix / scope indexing
    _q = qname.replace("::", ".")
    _s = scope.replace("::", ".")
    _cs = class_scope.replace("::", ".")

    # Scope-qualified suffix lookup (O(1))
    if _s and scope_suffix_index:
        key = (_s, _q)
        r = scope_suffix_index.get(key)
        if r is None and _cs:
            r = scope_suffix_index.get((_cs, _q))
        if r is not None:
            if resolve_cache is not None:
                resolve_cache[cache_key] = list(r)
            return list(r)

    # C translation-unit scope: same-file symbols first, via an O(1)
    # per-file index — common `static` names would otherwise scan the whole
    # cross-file suffix list per reference. Full qnames never reach this
    # branch (exact match above); cross-file statics of the fallback are
    # dropped by the caller, which knows the include closure.
    if fid and file_suffix_index is not None:
        r = file_suffix_index.get((fid, _q))
        if r:
            result = list(r)
            if resolve_cache is not None:
                resolve_cache[cache_key] = result
            return result

    r = suffix_index.get(_q)
    if r:
        result = list(r)
        if scope and len(result) > 1:
            scoped = [
                i
                for i in result
                if node_id_map.get(i, NodeInfo()).qualified_name.startswith(scope)
            ]
            if scoped:
                # Scoped result is only the caller itself; retain scoped match.
                only_self = (
                    len(scoped) == 1
                    and node_id_map.get(scoped[0], NodeInfo()).qualified_name == scope
                )
                if not only_self:
                    if resolve_cache is not None:
                        resolve_cache[cache_key] = scoped
                    return scoped
                if resolve_cache is not None:
                    resolve_cache[cache_key] = scoped
                return scoped
        if resolve_cache is not None:
            resolve_cache[cache_key] = result
        return result
    if resolve_cache is not None:
        resolve_cache[cache_key] = []
    return []


def _drop_cross_file_static(
    target_ids: list[int],
    source_fid: int,
    node_id_map: dict[int, NodeInfo],
    included_fids: Optional[set[int]] = None,
) -> list[int]:
    """Drop C internal-linkage (``static``) targets outside the source TU.

    A ``static`` in a header is per-TU: every including translation unit
    gets its own copy, so targets in files the source file (transitively)
    includes stay reachable. Non-static targets are always kept.
    """
    included = included_fids or set()
    return [
        t for t in target_ids
        if not (
            node_id_map.get(t)
            and node_id_map[t].visibility == "static"
            and node_id_map[t].file_id != source_fid
            and node_id_map[t].file_id not in included
        )
    ]


def _build_file_edges_worker(
    fp: str,
    pr: ParseResult,
    fnodes: dict[str, int],
    fid: int,
    module_qname: str,
    symbol_index: dict[str, list[int]],
    suffix_index: dict[str, list[int]],
    node_id_map: dict[int, NodeInfo],
    config: dict[str, Any],
    resolve_cache: Optional[dict] = None,
    scope_suffix_index: Optional[dict[tuple[str, str], list[int]]] = None,
    file_suffix_index: Optional[dict[tuple[int, str], list[int]]] = None,
    include_closure: Optional[dict[int, set[int]]] = None,
) -> list[EdgeInfo]:
    """Build directed edges from pre-collected references (no AST re-walk).

    For each reference in the parse result, resolves the target symbol
    and creates a directed edge between the source and target nodes.
    Module-level references from unregistered source nodes are assigned
    to the module pseudo-node (id=0).
    """
    edges: list[EdgeInfo] = []
    c_file = fp.endswith((".c", ".h"))
    included = include_closure.get(fid, ()) if include_closure else ()
    for ref in pr.references:
        source_id = fnodes.get(ref.source_qname, 0)
        if not source_id:
            if ref.source_qname == module_qname and ref.edge_type in ("read", "call"):
                source_id = 0
            else:
                continue
        source_node = node_id_map.get(source_id) if source_id else None
        scope = source_node.qualified_name if source_node else ""
        class_scope = ""
        if source_node and source_node.parent_node_id:
            parent = node_id_map.get(source_node.parent_node_id)
            if parent:
                class_scope = parent.qualified_name
        target_ids = _resolve_symbol(
            ref.target_name, scope,
            symbol_index, suffix_index, node_id_map,
            resolve_cache=resolve_cache,
            scope_suffix_index=scope_suffix_index,
            class_scope=class_scope,
            fid=fid if c_file else 0,
            file_suffix_index=file_suffix_index,
        )
        if c_file:
            # Internal linkage applies outside the TU; symbols in files the
            # TU (transitively) includes are per-TU copies and stay reachable.
            target_ids = _drop_cross_file_static(
                target_ids, fid, node_id_map, included
            )
        for tid in target_ids:
            if tid != source_id:
                edges.append(EdgeInfo(source_id, tid, ref.edge_type, fid, ref.line))

    return edges


# ---------------------------------------------------------------------------
# GraphBuilder
# ---------------------------------------------------------------------------


class GraphBuilder:
    """Dependency graph constructor."""

    def __init__(
        self,
        warning_collector: WarningCollector,
        registry: Optional[LanguageRegistry] = None,
        config: dict[str, Any] | None = None,
    ) -> None:
        self._nodes: list[NodeInfo] = []
        self._edges: list[EdgeInfo] = []
        self._symbol_index: defaultdict[str, list[int]] = defaultdict(list)
        self._suffix_index: defaultdict[str, list[int]] = defaultdict(list)
        self._scope_suffix_index: defaultdict[tuple[str, str], list[int]] = defaultdict(list)
        # Per-file simple-name index for C translation-unit-scope resolution.
        self._file_suffix_index: defaultdict[tuple[int, str], list[int]] = defaultdict(list)
        self._next_node_id: int = 1
        self._node_id_map: dict[int, NodeInfo] = {}
        self._old_to_new: dict[tuple[str, str], int] = {}
        self._include_fids: Optional[dict[int, list[int]]] = None
        self.warning_collector = warning_collector
        self.config = config or {}
        self.registry = registry

    def add_node(self, node: NodeInfo, preserve_id: bool = False) -> int:
        """Add a node and return its assigned ID."""
        if preserve_id and node.id:
            nid = node.id
            if nid >= self._next_node_id:
                self._next_node_id = nid + 1
        else:
            nid = self._next_node_id
            self._next_node_id += 1
        saved = NodeInfo(
            id=nid,
            file_id=node.file_id,
            name=node.name,
            qualified_name=node.qualified_name,
            node_type=node.node_type,
            line_start=node.line_start,
            line_end=node.line_end,
            col_offset=node.col_offset,
            parent_node_id=node.parent_node_id,
            is_deprecated=node.is_deprecated,
            deprecation_msg=node.deprecation_msg,
            type_annotation=node.type_annotation,
            is_async=node.is_async,
            decorators=list(node.decorators or []),
            docstring=node.docstring,
            is_entry=node.is_entry,
            is_partial=node.is_partial,
            canonical_name=node.canonical_name,
            visibility=node.visibility,
        )
        self._old_to_new[(str(node.file_id), str(node.id))] = nid
        self._nodes.append(saved)
        self._node_id_map[nid] = saved
        if node.file_id:
            self._file_suffix_index[(node.file_id, node.name)].append(nid)
        qname = node.qualified_name
        if qname:
            self._symbol_index[qname].append(nid)
            # Normalize multi-language separators (Python "." / Rust "::")
            # to "." for unified suffix-index lookups.
            normalized = qname.replace("::", ".")
            parts = normalized.split(".")
            for i in range(len(parts)):
                suffix = ".".join(parts[i:])
                self._suffix_index[suffix].append(nid)
                for j in range(i + 1):
                    scope = ".".join(parts[:j])
                    self._scope_suffix_index[(scope, suffix)].append(nid)
        return nid

    def add_edge(
        self,
        source_id: int,
        target_id: int,
        edge_type: str,
        file_id: int = 0,
        line: int = 0,
        context: str = "",
    ) -> None:
        """Add an edge."""
        self._edges.append(
            EdgeInfo(
                source_id=source_id,
                target_id=target_id,
                edge_type=edge_type,
                file_id=file_id,
                line=line,
                context=context,
            )
        )

    def build(
        self,
        parse_results: dict[str, ParseResult],
        changed_files: Optional[set[str]] = None,
        prebuilt_edges: Optional[list[EdgeInfo]] = None,
        prebuilt_entries: Optional[list[EntryInfo]] = None,
        old_changed_node_ids: dict[int, tuple[str, str]] | None = None,
        old_reachable: Optional[set[int]] = None,
        old_expanded: Optional[set[int]] = None,
    ) -> GraphBuildResult:
        """Build the complete dependency graph from parse results.

        Args:
            old_changed_node_ids: Maps old global node ID → (qualified_name, file_path)
                for nodes in changed files. Used to remap parent_node_id when a
                child in an unchanged file references a parent in a changed file.
            prebuilt_entries: Pre-loaded EntryInfo from DB for unchanged files
                (incremental mode). When provided, entry detection only scans
                changed files and merges these prebuilt entries.
            old_reachable: Reachable node IDs from the previous build
                (incremental mode). Enables component-level delta reachability.
            old_expanded: Expanded node IDs from the previous build
                (incremental mode). Used together with old_reachable.
        """
        fid_map: dict[str, int] = {}
        fid_cnt = 1
        if changed_files is None:
            changed_files = set(parse_results)

        # Build reverse lookup: (qualified_name, file_path) → old_id for changed file nodes
        qn_fp_to_old: dict[tuple[str, str], int] = {}
        if old_changed_node_ids:
            for old_id, (qn, fp) in old_changed_node_ids.items():
                qn_fp_to_old[(qn, fp)] = old_id

        # Start new node IDs above max preserved ID from unchanged files.
        max_preserved_id = 0
        for fp, pr in parse_results.items():
            if fp not in changed_files:
                for ni in pr.nodes:
                    if ni.id > max_preserved_id:
                        max_preserved_id = ni.id
        if max_preserved_id > 0:
            self._next_node_id = max_preserved_id + 1

        # Map old global ID → new global ID for changed file nodes
        old_to_new_global: dict[int, int] = {}

        for fp, pr in parse_results.items():
            fid = fid_cnt
            fid_cnt += 1
            fid_map[fp] = fid
            preserve = fp not in changed_files
            for ni in pr.nodes:
                ni.file_id = fid
                new_id = self.add_node(ni, preserve_id=preserve)
                if not preserve:
                    old_nid = qn_fp_to_old.get((ni.qualified_name, fp))
                    if old_nid:
                        old_to_new_global[old_nid] = new_id

        # Remap parent_node_id from per-file IDs to global IDs
        for n in self._nodes:
            if n.parent_node_id:
                # Case 1: same-file parent (per-file ID → global ID)
                key = (str(n.file_id), str(n.parent_node_id))
                mapped = self._old_to_new.get(key)
                if mapped:
                    n.parent_node_id = mapped
                # Case 2: cross-file parent in changed file
                # (old global ID → new global ID)
                elif old_to_new_global and n.parent_node_id in old_to_new_global:
                    n.parent_node_id = old_to_new_global[n.parent_node_id]

        # Merge partial class nodes (C#) into virtual merged nodes.
        self._merge_partial_nodes()

        changed_list = [fp for fp in changed_files if fp in parse_results]

        # Pre-build file_id → nodes index for fnodes lookups
        changed_fids = {fid_map[fp] for fp in changed_list if fp in fid_map}
        file_nodes_by_fid: dict[int, list[NodeInfo]] = {}
        for n in self._nodes:
            if n.file_id in changed_fids:
                file_nodes_by_fid.setdefault(n.file_id, []).append(n)

        # Build fnodes for all changed files (qualified_name → node_id)
        fnodes_map: dict[str, dict[str, int]] = {}
        for fp in changed_list:
            fid = fid_map.get(fp, 0)
            if fid and fid in file_nodes_by_fid:
                # First-writer-wins; a function overwrites a same-qname
                # non-function (an anonymous struct sharing the enclosing
                # symbol's qname must not steal a function's node id).
                fnodes_for_fp: dict[str, int] = {}
                for n in file_nodes_by_fid[fid]:
                    if n.qualified_name not in fnodes_for_fp:
                        fnodes_for_fp[n.qualified_name] = n.id
                    elif n.node_type == "function":
                        fnodes_for_fp[n.qualified_name] = n.id
                fnodes_map[fp] = fnodes_for_fp

        # C #include graph: a header included by a live file counts as live,
        # and the transitive closure feeds per-TU resolution (a header
        # `static` is reachable from every file that includes it).
        include_fids: dict[int, list[int]] = {}
        _pr_keys = set(parse_results)
        _base_index: dict[str, list[str]] = {}
        for _k in _pr_keys:
            _base_index.setdefault(os.path.basename(_k), []).append(_k)
        for _fp, _pr in parse_results.items():
            _fid = fid_map.get(_fp, 0)
            if not _fid:
                continue
            for _imp in _pr.imports or []:
                _inc = getattr(_imp, "include_path", "") or ""
                if not _inc:
                    continue
                _tgt = self._resolve_include(_inc, _fp, _pr_keys, _base_index)
                if _tgt and _tgt in fid_map and fid_map[_tgt] != _fid:
                    include_fids.setdefault(_fid, []).append(fid_map[_tgt])
        self._include_fids = include_fids
        include_closure: dict[int, set[int]] = {}
        for _fid in include_fids:
            _seen: set[int] = set()
            _stack = list(include_fids[_fid])
            while _stack:
                _cur = _stack.pop()
                if _cur in _seen:
                    continue
                _seen.add(_cur)
                _stack.extend(include_fids.get(_cur, ()))
            include_closure[_fid] = _seen

        # Detect entries via language adapters; in incremental mode only
        # changed files are scanned and prebuilt DB entries merged in.
        entries: list[EntryInfo] = []
        if prebuilt_entries is not None and changed_files and len(changed_files) < len(parse_results):
            changed_pr = {
                fp: pr for fp, pr in parse_results.items() if fp in changed_files
            }
            if self.registry:
                # Tell the C detector whether prebuilt entries already
                # include program entry points, so its auto library-mode
                # heuristic doesn't misfire on incremental builds of
                # executable projects (via a config copy — the shared
                # config object is never mutated here).
                detect_config = {
                    **self.config,
                    "_c_has_program_entries": any(
                        e.no_propagate is False for e in prebuilt_entries
                    ),
                }
                for adapter in self.registry.all_adapters():
                    entries.extend(
                        adapter.detect_entries(
                            self._adapter_parse_results(adapter, changed_pr),
                            self._nodes, self._node_id_map, detect_config,
                        )
                    )
            entries.extend(prebuilt_entries)
        else:
            if self.registry:
                for adapter in self.registry.all_adapters():
                    entries.extend(
                        adapter.detect_entries(
                            self._adapter_parse_results(adapter, parse_results),
                            self._nodes, self._node_id_map, self.config,
                        )
                    )
        for e in entries:
            if e.node_id and e.node_id in self._node_id_map:
                self._node_id_map[e.node_id].is_entry = True

        # Resolve node_id=0 entries to their global node IDs by file path
        # and line; unresolved ones stay file-level entries.
        for e in entries:
            if e.node_id == 0 and e.line > 0 and e.file_path:
                e_fid = fid_map.get(e.file_path, 0)
                if e_fid:
                    for n in self._nodes:
                        if n.file_id == e_fid and n.line_start == e.line:
                            e.node_id = n.id
                            self._node_id_map[n.id].is_entry = True
                            break

        self._edges = self._build_edges_batch(
            changed_list, parse_results, fid_map, fnodes_map,
            include_closure=include_closure,
        )
        # The edge batch replaces self._edges; re-attach the partial-fragment
        # part_of edges.
        self._add_partial_edges()
        new_edge_count = len(self._edges)

        # Add synthetic module-level edges through the module pseudo-node (id=0).
        # Index top-level nodes per file first — the naive double loop is
        # O(files × nodes) and dominates on large codebases.
        _top_nodes_by_fid: dict[int, list[int]] = {}
        for _n in self._nodes:
            if _n.parent_node_id == 0:
                _top_nodes_by_fid.setdefault(_n.file_id, []).append(_n.id)
        for fp in parse_results:
            _fid = fid_map.get(fp, 0)
            if _fid:
                for _nid in _top_nodes_by_fid.get(_fid, ()):
                    self.add_edge(0, _nid, "read", _fid, 0)

        _changed_old_ids = set(old_to_new_global) if old_to_new_global else set()
        _all_old_ids = set(old_changed_node_ids) if old_changed_node_ids else set()
        _removed_ids = _all_old_ids - (_changed_old_ids if old_to_new_global else set())

        if prebuilt_edges:
            for pe in prebuilt_edges:
                sid, tid = pe.source_id, pe.target_id
                if sid in _changed_old_ids:
                    sid = old_to_new_global.get(sid, 0)
                if tid in _changed_old_ids:
                    tid = old_to_new_global.get(tid, 0)
                if sid in _removed_ids:
                    sid = 0
                if tid in _removed_ids:
                    tid = 0
                if sid and tid:
                    pe.source_id = sid
                    pe.target_id = tid
                    self._edges.append(pe)

        expanded: set[int] = set()
        reachable: set[int] = set()

        # Rebuild genuine module-level use edges (source 0) for unchanged
        # files from restored references. The edges table cannot hold them
        # (its source_id references nodes; node 0 does not exist), so they
        # round-trip through the imports table.
        if changed_files is not None and changed_files != set(parse_results):
            for _fp, _pr in parse_results.items():
                if _fp in changed_files:
                    continue
                _fid = fid_map.get(_fp, 0)
                if not _fid:
                    continue
                for _ref in _pr.references:
                    if not _ref.target_name:
                        continue
                    _tids = _resolve_symbol(
                        _ref.target_name,
                        "",
                        self._symbol_index,
                        self._suffix_index,
                        self._node_id_map,
                    )
                    if _fp.endswith((".c", ".h")):
                        _tids = _drop_cross_file_static(
                            _tids, _fid, self._node_id_map,
                            include_closure.get(_fid, ()),
                        )
                    for _tid in _tids:
                        self._edges.append(
                            EdgeInfo(0, _tid, _ref.edge_type, _fid, _ref.line)
                        )

        _sn = self._get_special_names()
        _pn = self._get_public_api_names()
        special_check = self._make_special_name_check(fid_map, _sn)
        public_check = self._make_public_api_check(fid_map, _pn)
        _cached_adj = _build_undirected_adj(
            self._edges, self._node_id_map, _sn, _pn,
            is_special_name=special_check, is_public_api_name=public_check,
        )
        _cached_cg = _build_call_graph(self._edges, self._node_id_map)
        _cached_csm = _build_class_special_map(
            self._node_id_map, _sn, is_special_name=special_check,
        )
        _cached_dg = _build_digraph(self._nodes, self._edges)

        changed_nids: Optional[set[int]] = None
        if changed_files is not None and old_reachable is not None:
            changed_fids = {fid_map[fp] for fp in changed_files if fp in fid_map}
            changed_nids = {
                n.id for n in self._nodes if n.file_id in changed_fids
            }

        comp_map, comps = find_connected_components(
            self._nodes,
            self._edges,
            self._node_id_map,
            entries,
            fid_map,
            public_api_names=_pn,
            special_method_names=_sn,
            expanded_out=expanded,
            changed_node_ids=changed_nids,
            old_reachable=old_reachable,
            reachable_out=reachable,
            cached_adj=_cached_adj,
            cached_call_graph=_cached_cg,
            cached_class_special_map=_cached_csm,
            is_special_name=special_check,
            is_public_api_name=public_check,
            include_fids=include_fids,
        )
        file_id_to_path = {v: k for k, v in fid_map.items()}
        self._add_warnings(comps, file_id_to_path, cached_digraph=_cached_dg,
                           special_names=_sn, public_api_names=_pn)

        return GraphBuildResult(
            nodes=list(self._nodes),
            edges=list(self._edges),
            warnings=self.warning_collector.get_all(),
            files=list(parse_results.keys()),
            files_data=dict(parse_results),
            entry_info_list=entries,
            component_map=comp_map,
            components=comps,
            node_id_map=dict(self._node_id_map),
            expanded=expanded,
            reachable=reachable,
            remapped_node_ids=dict(old_to_new_global),
            new_edge_count=new_edge_count,
        )

    def _build_edges_batch(
        self,
        changed_list: list[str],
        parse_results: dict[str, ParseResult],
        fid_map: dict[str, int],
        fnodes_map: dict[str, dict[str, int]],
        include_closure: Optional[dict[int, set[int]]] = None,
    ) -> list[EdgeInfo]:
        """Build edges for a batch of files (parallel or sequential)."""
        all_edges: list[EdgeInfo] = []
        pw = self.config.get("performance", {}).get("parallel_workers", 0) or 0
        if pw > 1 and len(changed_list) > 1:
            with ProcessPoolExecutor(max_workers=min(pw, len(changed_list))) as ex:
                futs = {}
                for fp in changed_list:
                    pr = parse_results[fp]
                    fnodes = fnodes_map.get(fp, {})
                    # Pre-compute module_qname via adapter
                    module_qname = self._module_qname_for(fp)

                    futs[
                        ex.submit(
                            _build_file_edges_worker,
                            fp, pr, fnodes, fid_map[fp], module_qname,
                            self._symbol_index, self._suffix_index,
                            self._node_id_map, self.config,
                            {},  # Per-worker independent resolve cache
                            self._scope_suffix_index,
                            self._file_suffix_index,
                            include_closure,
                        )
                    ] = fp
                for fut in as_completed(futs):
                    try:
                        all_edges.extend(fut.result())
                    except Exception:
                        pass
        else:
            for fp in changed_list:
                pr = parse_results[fp]
                fnodes = fnodes_map.get(fp, {})
                fid = fid_map.get(fp, 0)
                module_qname = self._module_qname_for(fp)
                all_edges.extend(
                    _build_file_edges_worker(
                        fp, pr, fnodes, fid, module_qname,
                        self._symbol_index, self._suffix_index,
                        self._node_id_map, self.config,
                        {},
                        self._scope_suffix_index,
                        self._file_suffix_index,
                        include_closure,
                    )
                )
        return all_edges

    def _module_qname_for(self, file_path: str) -> str:
        """Convert file path to module qname using the registered language adapter."""
        if self.registry:
            adapter = self.registry.adapter_for_file(file_path)
            if adapter:
                return adapter.file_to_module_with_csproj(file_path, self.config)
        return file_path

    @staticmethod
    def _adapter_parse_results(
        adapter: LanguageAdapter,
        parse_results: dict[str, ParseResult],
    ) -> dict[str, ParseResult]:
        """Restrict parse results to the adapter's own file extensions.

        Without the filter every adapter iterates every project file and
        applies every entry rule — the Python detector even re-parses .c
        files as Python.
        """
        exts = adapter.file_extensions
        if not exts:
            return parse_results
        return {
            fp: pr for fp, pr in parse_results.items()
            if fp.endswith(tuple(exts))
        }

    @staticmethod
    def _resolve_include(
        include_path: str,
        from_file: str,
        parse_keys: set[str],
        base_index: dict[str, list[str]],
    ) -> str:
        """Resolve an ``#include`` path to a parsed file key.

        Tries the raw path, the including file's directory, then a unique
        basename match (O(1) via ``base_index``). Returns ``""`` when
        unresolvable.
        """
        if include_path in parse_keys:
            return include_path
        cand = os.path.normpath(
            os.path.join(os.path.dirname(from_file), include_path)
        ).replace(os.sep, "/")
        if cand in parse_keys:
            return cand
        matches = base_index.get(os.path.basename(include_path), ())
        if len(matches) == 1:
            return matches[0]
        return ""

    # ------------------------------------------------------------------
    # Partial class merging (C#)
    # ------------------------------------------------------------------

    def _merge_partial_nodes(self) -> None:
        """Merge C# partial class/struct/record nodes into virtual merged
        nodes.

        For partial types defined across multiple files, each file produces
        a node with ``is_partial=True`` and a file-unique qualified_name
        (e.g. ``Ns.Foo#partial:src/Part1.cs``).  This method groups those
        nodes by their ``canonical_name`` (the logical type name, e.g.
        ``Ns.Foo``), creates one virtual merged node per group, and remaps
        the symbol indices so that all references resolve to the merged node.

        The individual partial nodes retain their internal structure
        (methods, fields, etc.) so that file-local edges remain correct.
        """
        # Group partial nodes by (canonical_name, node_type)
        groups: dict[tuple[str, str], list[NodeInfo]] = defaultdict(list)
        for n in self._nodes:
            if n.is_partial and n.canonical_name:
                key = (n.canonical_name, n.node_type)
                groups[key].append(n)

        if not groups:
            return

        for (canonical, node_type), partial_nodes in groups.items():
            if len(partial_nodes) < 1:
                continue

            # Determine representative metadata
            min_line = min(n.line_start for n in partial_nodes if n.line_start > 0)
            all_decorators: list[str] = []
            seen_dec: set[str] = set()
            for n in partial_nodes:
                for d in n.decorators:
                    if d not in seen_dec:
                        seen_dec.add(d)
                        all_decorators.append(d)

            # Use the first partial node's file_id for the merged node
            # (virtual nodes need a file association for DB persistence).
            existing_ids = self._symbol_index.get(canonical, [])
            existing_merged = None
            for eid in existing_ids:
                en = self._node_id_map.get(eid)
                if en and not en.is_partial and en.qualified_name == canonical:
                    existing_merged = en
                    break

            if existing_merged is not None:
                merged_id = existing_merged.id
                merged = existing_merged
                # Update metadata from current partial parts
                merged.decorators = all_decorators
                merged.docstring = "[partial merged: {} files]".format(len(partial_nodes))
                merged.line_start = min_line
                merged.line_end = max(n.line_end for n in partial_nodes)
            else:
                rep_file_id = partial_nodes[0].file_id
                merged_id = self._next_node_id
                self._next_node_id += 1
                merged = NodeInfo(
                    id=merged_id,
                    file_id=rep_file_id,
                    name=canonical.split(".")[-1] if "." in canonical else canonical,
                    qualified_name=canonical,
                    node_type=node_type,
                    line_start=min_line,
                    line_end=max(n.line_end for n in partial_nodes),
                    col_offset=0,
                    parent_node_id=0,
                    decorators=all_decorators,
                    docstring="[partial merged: {} files]".format(len(partial_nodes)),
                    is_partial=False,
                    canonical_name="",
                    visibility=partial_nodes[0].visibility,
                )
                self._nodes.append(merged)
                self._node_id_map[merged_id] = merged

            # Remap symbol indices from partial nodes to the merged node.
            for pn in partial_nodes:
                qn = pn.qualified_name
                if qn in self._symbol_index:
                    self._symbol_index[qn] = [
                        i for i in self._symbol_index.get(qn, []) if i != pn.id
                    ]
                    if not self._symbol_index[qn]:
                        del self._symbol_index[qn]

            # Add merged node to indices under the canonical name
            self._symbol_index[canonical].insert(0, merged_id)

            # Update suffix indices
            normalized = canonical.replace("::", ".")
            parts = normalized.split(".")
            for i in range(len(parts)):
                suffix = ".".join(parts[i:])
                self._suffix_index[suffix].insert(0, merged_id)
                for j in range(i + 1):
                    scope = ".".join(parts[:j])
                    self._scope_suffix_index[(scope, suffix)].insert(0, merged_id)

    def _add_partial_edges(self) -> None:
        """Attach ``part_of`` edges from partial fragments to their
        merged node.

        Called *after* the edge batch replaces :attr:`_edges` — the batch is
        built from parse-result references only, so the fragment→merged links
        created by :meth:`_merge_partial_nodes` would otherwise be lost.  These
        edges let reachability flow between fragments and the merged type.
        """
        for n in self._nodes:
            if not (n.is_partial and n.canonical_name):
                continue
            ids = self._symbol_index.get(n.canonical_name, [])
            merged_id = ids[0] if ids else 0
            if merged_id and merged_id != n.id:
                self.add_edge(n.id, merged_id, "part_of", n.file_id, n.line_start)

    # ------------------------------------------------------------------
    # Public / special name helpers
    # ------------------------------------------------------------------

    def _get_public_api_names(self) -> frozenset[str]:
        if self.registry:
            return self.registry.public_api_names()
        return frozenset()

    def _get_special_names(self) -> frozenset[str]:
        if self.registry:
            return self.registry.special_names()
        return frozenset()

    def _make_special_name_check(
        self, fid_map: dict[str, int], fallback: frozenset[str]
    ) -> Callable[[NodeInfo], bool]:
        """Return a per-node special-name checker scoped to the node's
        language.

        Language-specific special names (e.g. C# ``Dispose`` / ``ToString``,
        Rust ``drop``) must not leak into other languages' analysis: a Python
        method named ``Dispose`` is an ordinary method, not an implicitly
        invoked one.  The checker resolves each node's file to its language
        adapter and delegates to ``adapter.is_special_name``; nodes in files
        with no registered adapter fall back to the legacy union set.
        """
        registry = self.registry
        path_by_fid = {fid: fp for fp, fid in fid_map.items()}
        adapter_cache: dict[int, Any] = {}

        def check(node: NodeInfo) -> bool:
            if registry is None:
                return node.name in fallback
            fid = node.file_id
            if fid not in adapter_cache:
                fp = path_by_fid.get(fid, "")
                adapter = registry.adapter_for_file(fp) if fp else None
                adapter_cache[fid] = adapter
            adapter = adapter_cache[fid]
            if adapter is None:
                return node.name in fallback
            return adapter.is_special_name(node.name)

        return check

    def _make_public_api_check(
        self, fid_map: dict[str, int], fallback: frozenset[str]
    ) -> Callable[[NodeInfo], bool]:
        """Return a per-node public-API-name checker scoped to the
        node's language.

        Mirrors :meth:`_make_special_name_check` for public API names so that
        e.g. C# ``Main`` is not treated as a public-API name inside Python
        code.
        """
        registry = self.registry
        path_by_fid = {fid: fp for fp, fid in fid_map.items()}
        adapter_cache: dict[int, Any] = {}

        def check(node: NodeInfo) -> bool:
            if registry is None:
                return node.name in fallback
            fid = node.file_id
            if fid not in adapter_cache:
                fp = path_by_fid.get(fid, "")
                adapter = registry.adapter_for_file(fp) if fp else None
                adapter_cache[fid] = adapter
            adapter = adapter_cache[fid]
            if adapter is None:
                return node.name in fallback
            return node.name in adapter.public_api_names

        return check

    def _node_is_special(
        self,
        node: NodeInfo,
        file_id_to_path: dict[int, str],
        fallback: frozenset[str],
    ) -> bool:
        """True when *node* has a special name *for its own language*.

        Special-name semantics are language-specific; a name that is
        implicitly invoked in one language (C# ``Dispose``) is an ordinary
        method in another.  Nodes in files without a registered adapter fall
        back to the legacy cross-language union set.
        """
        if self.registry is None:
            return node.name in fallback
        fp = file_id_to_path.get(node.file_id, "")
        adapter = self.registry.adapter_for_file(fp) if fp else None
        if adapter is None:
            return node.name in fallback
        return adapter.is_special_name(node.name)

    def _node_is_public_api(
        self,
        node: NodeInfo,
        file_id_to_path: dict[int, str],
        fallback: frozenset[str],
    ) -> bool:
        """True when *node* has a public-API name *for its own language*."""
        if self.registry is None:
            return node.name in fallback
        fp = file_id_to_path.get(node.file_id, "")
        adapter = self.registry.adapter_for_file(fp) if fp else None
        if adapter is None:
            return node.name in fallback
        return node.name in adapter.public_api_names
 
    def _add_warnings(
        self,
        comps: list[ComponentInfo],
        file_id_to_path: Optional[dict[int, str]] = None,
        cached_digraph: Optional[dict[int, list[int]]] = None,
        special_names: Optional[frozenset[str]] = None,
        public_api_names: Optional[frozenset[str]] = None,
    ) -> None:
        """Collect all warning types."""
        if file_id_to_path is None:
            file_id_to_path = {}

        if special_names is None or public_api_names is None:
            if self.registry:
                if special_names is None:
                    special_names = self.registry.special_names()
                if public_api_names is None:
                    public_api_names = self.registry.public_api_names()
            else:
                if special_names is None:
                    special_names = frozenset()
                if public_api_names is None:
                    public_api_names = frozenset()

        for w in detect_write_only_nodes(
            self._nodes, self._edges, self._node_id_map, file_id_to_path,
            public_api_names=public_api_names,
        ):
            self.warning_collector.add(
                w.warn_type,
                w.severity,
                w.message,
                w.file_path,
                w.line,
                w.node_id,
                w.details,
            )
        for w in detect_circular_refs(self._nodes, self._edges, self._node_id_map, cached_digraph=cached_digraph):
            self.warning_collector.add(
                w.warn_type,
                w.severity,
                w.message,
                w.file_path,
                w.line,
                w.node_id,
                w.details,
            )
        for comp in comps:
            if comp.is_unreachable:
                special_method_nids = [
                    nid
                    for nid in comp.node_ids
                    if nid in self._node_id_map
                    and self._node_is_special(
                        self._node_id_map[nid], file_id_to_path, special_names
                    )
                ]
                non_dunder_nids = [
                    nid
                    for nid in comp.node_ids
                    if nid in self._node_id_map
                    and not self._node_is_public_api(
                        self._node_id_map[nid], file_id_to_path, public_api_names
                    )
                    and self._node_id_map[nid].name != "_"
                    and not self._node_id_map[nid].is_partial
                    and nid not in special_method_nids
                ]
                # Skip only-dunder components.
                if not non_dunder_nids and not special_method_nids:
                    continue
                # Warn about dead code for non-dunder nodes (classes, functions, etc.)
                for nid in sorted(non_dunder_nids)[:3]:
                    node = self._node_id_map.get(nid)
                    if node:
                        fp = file_id_to_path.get(node.file_id, "")
                        self.warning_collector.add(
                            "dead_code",
                            "info",
                            f"Component {comp.component_id}: "
                            f"unreachable — no CALL path from entry point",
                            file_path=fp,
                            line=node.line_start,
                            node_id=nid,
                        )
                # Warn about isolated special methods when component has no
                # non-dunder nodes.
                if special_method_nids and not non_dunder_nids:
                    for nid in sorted(special_method_nids)[:2]:
                        node = self._node_id_map.get(nid)
                        if node:
                            fp = file_id_to_path.get(node.file_id, "")
                            self.warning_collector.add(
                                "dead_code",
                                "info",
                                f"Component {comp.component_id}: "
                                f"special method '{node.name}' overload has no "
                                f"explicit CALL path (functional completeness)",
                                file_path=fp,
                                line=node.line_start,
                                node_id=nid,
                            )
        self.warning_collector.deduplicate()

    def get_all_data(self) -> GraphBuildResult:
        """Return all built data (used by tests)."""
        expanded: set[int] = set()
        reachable: set[int] = set()
        cm, cs = find_connected_components(
            self._nodes,
            self._edges,
            self._node_id_map,
            [],
            {},
            public_api_names=self._get_public_api_names(),
            special_method_names=self._get_special_names(),
            expanded_out=expanded,
            reachable_out=reachable,
            include_fids=self._include_fids,
        )
        return GraphBuildResult(
            nodes=list(self._nodes),
            edges=list(self._edges),
            warnings=self.warning_collector.get_all(),
            component_map=cm,
            components=cs,
            node_id_map=dict(self._node_id_map),
            expanded=expanded,
            reachable=reachable,
        )
