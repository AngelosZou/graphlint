# -*- coding: utf-8 -*-
"""Dependency graph builder — builds directed/undirected edges, detects circular references and connected components."""

from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Any, Optional

from graphlint.analyzer._graph_algo import (
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
) -> list[int]:
    """Resolve a symbol by exact match first, then suffix match.

    Args:
        qname: The symbol simple name to resolve (e.g. ``"field_name"``).
        scope: Qualified name of the calling scope (e.g. ``"pkg.mod.MyClass.method"``).
        symbol_index: Exact qualified-name lookup table.
        suffix_index: Suffix-based lookup for partial matches.
        node_id_map: Global node ID to NodeInfo mapping.
        resolve_cache: Optional cache keyed by ``(qname, scope)``.
        scope_suffix_index: Optional ``(scope, simple_name)`` lookup table.
        class_scope: Fallback scope for class-level field resolution.

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

    # Scope-qualified suffix lookup (O(1))
    if scope and scope_suffix_index:
        key = (scope, qname)
        r = scope_suffix_index.get(key)
        if r is None and class_scope:
            r = scope_suffix_index.get((class_scope, qname))
        if r is not None:
            if resolve_cache is not None:
                resolve_cache[cache_key] = list(r)
            return list(r)

    r = suffix_index.get(qname)
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
) -> list[EdgeInfo]:
    """Build directed edges from pre-collected references (no AST re-walk).

    For each reference in the parse result, resolves the target symbol
    and creates a directed edge between the source and target nodes.
    Module-level references from unregistered source nodes are assigned
    to the module pseudo-node (id=0).
    """
    edges: list[EdgeInfo] = []
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
        self._next_node_id: int = 1
        self._node_id_map: dict[int, NodeInfo] = {}
        self._old_to_new: dict[tuple[str, str], int] = {}
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
        )
        self._old_to_new[(str(node.file_id), str(node.id))] = nid
        self._nodes.append(saved)
        self._node_id_map[nid] = saved
        qname = node.qualified_name
        if qname:
            self._symbol_index[qname].append(nid)
            parts = qname.split(".")
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
        old_changed_node_ids: dict[int, tuple[str, str]] | None = None,
    ) -> GraphBuildResult:
        """Build the complete dependency graph from parse results.

        Args:
            old_changed_node_ids: Maps old global node ID → (qualified_name, file_path)
                for nodes in changed files. Used to remap parent_node_id when a
                child in an unchanged file references a parent in a changed file.
        """
        fid_map: dict[str, int] = {}
        fid_cnt = 1
        changed_files = changed_files or set(parse_results)

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

        changed_list = [fp for fp in changed_files if fp in parse_results]

        # Pre-build file_id → nodes index for fnodes lookups
        file_nodes_by_fid: dict[int, list[NodeInfo]] = {}
        for n in self._nodes:
            file_nodes_by_fid.setdefault(n.file_id, []).append(n)

        # Build fnodes for all changed files (qualified_name → node_id)
        fnodes_map: dict[str, dict[str, int]] = {}
        for fp in changed_list:
            fid = fid_map.get(fp, 0)
            if fid and fid in file_nodes_by_fid:
                fnodes_map[fp] = {n.qualified_name: n.id for n in file_nodes_by_fid[fid]}

        # Detect entries via language adapters
        entries: list[EntryInfo] = []
        if self.registry:
            for adapter in self.registry.all_adapters():
                entries.extend(
                    adapter.detect_entries(
                        parse_results, self._nodes, self._node_id_map, self.config
                    )
                )
        for e in entries:
            if e.node_id and e.node_id in self._node_id_map:
                self._node_id_map[e.node_id].is_entry = True

        # Resolve function_def:/decorator: entries (node_id=0) to
        # their global node IDs by file path + line number.  Entries
        # with unresolved node_id are treated as file-level entries.
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
        )

        # Add synthetic module-level edges through the module pseudo-node (id=0).
        for fp in parse_results:
            _fid = fid_map.get(fp, 0)
            if _fid:
                for _n in self._nodes:
                    if _n.file_id == _fid and _n.parent_node_id == 0:
                        self.add_edge(0, _n.id, "read", _fid, 0)

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

        comp_map, comps = find_connected_components(
            self._nodes,
            self._edges,
            self._node_id_map,
            entries,
            fid_map,
            public_api_names=self._get_public_api_names(),
            special_method_names=self._get_special_names(),
        )
        file_id_to_path = {v: k for k, v in fid_map.items()}
        self._add_warnings(comps, file_id_to_path)

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
        )

    def _build_edges_batch(
        self,
        changed_list: list[str],
        parse_results: dict[str, ParseResult],
        fid_map: dict[str, int],
        fnodes_map: dict[str, dict[str, int]],
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
                    )
                )
        return all_edges

    def _module_qname_for(self, file_path: str) -> str:
        """Convert file path to module qname using the registered language adapter."""
        if self.registry:
            adapter = self.registry.adapter_for_file(file_path)
            if adapter:
                return adapter.file_to_module(file_path)
        return file_path

    def _get_public_api_names(self) -> frozenset[str]:
        if self.registry:
            return self.registry.public_api_names()
        return frozenset()

    def _get_special_names(self) -> frozenset[str]:
        if self.registry:
            return self.registry.special_names()
        return frozenset()

    def _add_warnings(
        self,
        comps: list[ComponentInfo],
        file_id_to_path: Optional[dict[int, str]] = None,
    ) -> None:
        """Collect all warning types."""
        if file_id_to_path is None:
            file_id_to_path = {}

        # Gather language-specific special names from adapters
        public_api_names: frozenset[str] = frozenset()
        special_names: frozenset[str] = frozenset()
        if self.registry:
            public_api_names = self.registry.public_api_names()
            special_names = self.registry.special_names()

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
        for w in detect_circular_refs(self._nodes, self._edges, self._node_id_map):
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
                    and self._node_id_map[nid].name in special_names
                ]
                non_dunder_nids = [
                    nid
                    for nid in comp.node_ids
                    if nid in self._node_id_map
                    and self._node_id_map[nid].name not in public_api_names
                    and self._node_id_map[nid].name != "_"
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
        cm, cs = find_connected_components(
            self._nodes,
            self._edges,
            self._node_id_map,
            [],
            {},
            public_api_names=self._get_public_api_names(),
            special_method_names=self._get_special_names(),
        )
        return GraphBuildResult(
            nodes=list(self._nodes),
            edges=list(self._edges),
            warnings=self.warning_collector.get_all(),
            component_map=cm,
            components=cs,
            node_id_map=dict(self._node_id_map),
        )
