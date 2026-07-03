# -*- coding: utf-8 -*-
"""Dependency graph builder — builds directed/undirected edges, detects circular references and connected components."""

from __future__ import annotations

import ast
import os
from dataclasses import dataclass, field
from typing import Any, Optional

from graphlint.analyzer._graph_algo import (
    detect_circular_refs,
    find_connected_components,
)
from graphlint.analyzer._types import ComponentInfo, EdgeInfo, NodeInfo, ParseResult
from graphlint.analyzer.decorators import DecoratorResolver
from graphlint.analyzer.entry_detect import EntryInfo, EntryPointDetector
from graphlint.analyzer.warnings import (
    WarningCollector,
    WarningInfo,
    _PUBLIC_API_DUNDERS,
    _SPECIAL_METHOD_DUNDERS,
    detect_write_only_nodes,
)


@dataclass
class GraphBuildResult:
    """Complete output of GraphBuilder.build()."""

    nodes: list[NodeInfo] = field(default_factory=list)
    edges: list[EdgeInfo] = field(default_factory=list)
    warnings: list[WarningInfo] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    files_data: dict[str, ParseResult] = field(default_factory=dict)
    entry_info_list: list[EntryInfo] = field(default_factory=list)
    component_map: dict[int, int] = field(default_factory=dict)
    components: list[ComponentInfo] = field(default_factory=list)
    node_id_map: dict[int, Any] = field(default_factory=dict)


class GraphBuilder:
    """Dependency graph constructor."""

    def __init__(
        self,
        warning_collector: WarningCollector,
        config: dict[str, Any] | None = None,
    ) -> None:
        self._nodes: list[NodeInfo] = []
        self._edges: list[EdgeInfo] = []
        self._symbol_index: dict[str, list[int]] = {}
        self._short_name_index: dict[str, list[int]] = {}
        self._next_node_id: int = 1
        self._node_id_map: dict[int, NodeInfo] = {}
        self._old_to_new: dict[tuple[str, str], int] = {}
        self.warning_collector = warning_collector
        self.config = config or {}
        self.entry_detector = EntryPointDetector(self.config)
        self.decorator_resolver = DecoratorResolver()

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
            self._symbol_index.setdefault(qname, []).append(nid)
            if "." in qname:
                short = qname.rsplit(".", 1)[-1]
                self._short_name_index.setdefault(short, []).append(nid)
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

        # Start new node IDs above the max preserved ID from unchanged files
        # to prevent ID collisions when unique IDs collide with preserved DB IDs
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

        # Only build edges for changed files; unchanged ones keep DB edges
        for fp in changed_files:
            if fp in parse_results:
                self._build_edges(fp, parse_results[fp], fid_map.get(fp, 0))

        # Merge prebuilt edges from DB for unchanged files (incremental mode)
        if prebuilt_edges:
            # Remap old node IDs in prebuilt edges to new IDs
            if old_to_new_global:
                _changed_old_ids = set(old_to_new_global)
                for _pe in prebuilt_edges:
                    if _pe.source_id in _changed_old_ids:
                        _pe.source_id = old_to_new_global.get(_pe.source_id, 0)
                    if _pe.target_id in _changed_old_ids:
                        _pe.target_id = old_to_new_global.get(_pe.target_id, 0)
            # Filter out edges referencing removed nodes (present in old
            # changed-file data but not in the new build). These old node IDs
            # would violate FK constraints during DB insertion.
            if old_changed_node_ids:
                _all_old_ids = set(old_changed_node_ids)
                _live_old_ids = set(old_to_new_global) if old_to_new_global else set()
                _removed_ids = _all_old_ids - _live_old_ids
                if _removed_ids:
                    for _pe in prebuilt_edges:
                        if _pe.source_id in _removed_ids:
                            _pe.source_id = 0
                        if _pe.target_id in _removed_ids:
                            _pe.target_id = 0
            for _pe in prebuilt_edges:
                if _pe.source_id and _pe.target_id:
                    self._edges.append(_pe)

        # Add synthetic module-level edges for unchanged files to reconnect
        # module-level nodes through the module pseudo-node (id=0).
        # Module-level edges (source_id=0) are not stored in the DB, so they
        # must be recreated in memory for correct component connectivity.
        if changed_files:
            for fp in parse_results:
                if fp not in changed_files:
                    _fid = fid_map.get(fp, 0)
                    if _fid:
                        _first = None
                        for _n in self._nodes:
                            if _n.file_id == _fid and _n.parent_node_id == 0:
                                if _first is None:
                                    _first = _n.id
                                self.add_edge(0, _n.id, "read", _fid, 0)

        entries = self.entry_detector.detect(
            parse_results,
            self._nodes,
            self._node_id_map,
        )
        for e in entries:
            if e.node_id and e.node_id in self._node_id_map:
                self._node_id_map[e.node_id].is_entry = True

        comp_map, comps = find_connected_components(
            self._nodes,
            self._edges,
            self._node_id_map,
            entries,
            fid_map,
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

    def _add_warnings(
        self,
        comps: list[ComponentInfo],
        file_id_to_path: Optional[dict[int, str]] = None,
    ) -> None:
        """Collect all warning types."""
        if file_id_to_path is None:
            file_id_to_path = {}
        for w in detect_write_only_nodes(
            self._nodes, self._edges, self._node_id_map, file_id_to_path
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
                    and self._node_id_map[nid].name in _SPECIAL_METHOD_DUNDERS
                ]
                non_dunder_nids = [
                    nid
                    for nid in comp.node_ids
                    if nid in self._node_id_map
                    and self._node_id_map[nid].name not in _PUBLIC_API_DUNDERS
                    and nid not in special_method_nids
                ]
                # If every node in the component is either a public API
                # dunder or a special method overload, skip entirely.
                if not non_dunder_nids and not special_method_nids:
                    continue
                # Warn about dead special method overloads (functional completeness)
                if special_method_nids:
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
                # Warn about other dead code nodes
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
        self.warning_collector.deduplicate()

    def _build_edges(
        self,
        fp: str,
        pr: ParseResult,
        fid: int,
    ) -> None:
        """Build edges for a single file."""
        src = pr.source
        if src is None:
            abs_p = os.path.join(self.config.get("_root_dir", os.getcwd()), fp)
            try:
                with open(abs_p, "r", encoding="utf-8") as fh:
                    src = fh.read()
            except OSError:
                return
        try:
            tree = ast.parse(src, filename=fp)
        except SyntaxError:
            return
        fnodes = self._file_node_index(fid)
        mq = fp.replace("/", ".").replace(".py", "")
        self._walk(tree, [0], fid, fnodes, mq)

    def _file_node_index(self, fid: int) -> dict[str, int]:
        """Build qualified_name → node_id map for the current file."""
        r: dict[str, int] = {}
        for n in self._nodes:
            if n.file_id == fid:
                r[n.qualified_name] = self._node_id_for(n)
        return r

    _STMT_WALK_TYPES = (
        ast.FunctionDef,
        ast.AsyncFunctionDef,
        ast.ClassDef,
        ast.Call,
        ast.Assign,
        ast.AnnAssign,
        ast.Expr,
        ast.Return,
        ast.Raise,
        ast.If,
        ast.While,
        ast.For,
        ast.With,
        ast.AugAssign,
        ast.Assert,
        ast.Delete,
        ast.Try,
    )

    def _walk(
        self,
        node: ast.AST,
        ctx: list[int],
        fid: int,
        fnodes: dict[str, int],
        mq: str,
    ) -> None:
        """Recursively walk AST to build edges."""
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            nid = fnodes.get(f"{mq}.{node.name}", 0)
            ctx.append(nid)
            for dec in node.decorator_list:
                dec_name = self._call_name(
                    dec.func if isinstance(dec, ast.Call) else dec
                )
                dec_ids = self._resolve_symbol(dec_name)
                for did in dec_ids:
                    if did != nid:
                        self.add_edge(nid, did, "decorate", fid, node.lineno)
            for item in node.body:
                self._walk(item, ctx, fid, fnodes, mq)
            ctx.pop()
        elif isinstance(node, ast.ClassDef):
            nid = fnodes.get(f"{mq}.{node.name}", 0)
            ctx.append(nid)
            old_mq = mq
            mq = f"{mq}.{node.name}"
            for base in node.bases:
                base_name = self._call_name(base)
                base_ids = self._resolve_symbol(base_name)
                for bid in base_ids:
                    if bid != nid:
                        self.add_edge(nid, bid, "inherit", fid, node.lineno)
            for dec in node.decorator_list:
                dec_name = self._call_name(
                    dec.func if isinstance(dec, ast.Call) else dec
                )
                dec_ids = self._resolve_symbol(dec_name)
                for did in dec_ids:
                    if did != nid:
                        self.add_edge(nid, did, "decorate", fid, node.lineno)
            for item in node.body:
                self._walk(item, ctx, fid, fnodes, mq)
            mq = old_mq
            ctx.pop()
        elif isinstance(node, ast.Call):
            self._proc_call(node, ctx, fid, fnodes, mq)
        elif isinstance(node, ast.Assign):
            self._proc_assign(node, ctx, fid, fnodes, mq)
        elif isinstance(node, ast.AnnAssign):
            self._proc_annassign(node, ctx, fid, mq)
        elif isinstance(node, ast.Expr):
            self._read_edges(node.value, ctx, fid, node.lineno)
        elif isinstance(node, ast.Return) and node.value:
            if isinstance(node.value, ast.Call):
                self._walk(node.value, ctx, fid, fnodes, mq)
            else:
                self._read_edges(node.value, ctx, fid, node.lineno)
        elif isinstance(node, ast.Raise) and node.exc:
            if isinstance(node.exc, ast.Call):
                self._walk(node.exc, ctx, fid, fnodes, mq)
            else:
                self._read_edges(node.exc, ctx, fid, node.lineno)
        elif isinstance(node, (ast.If, ast.While)):
            self._read_edges(node.test, ctx, fid, node.lineno)
        elif isinstance(node, ast.For):
            self._read_edges(node.iter, ctx, fid, node.lineno)
        elif isinstance(node, ast.With):
            for item in node.items:  # type: ignore[assignment]
                self._read_edges(item.context_expr, ctx, fid, node.lineno)  # type: ignore[attr-defined]
        elif isinstance(node, ast.AugAssign):
            self._read_edges(node.value, ctx, fid, node.lineno)
        elif isinstance(node, ast.Assert):
            self._read_edges(node.test, ctx, fid, node.lineno)
            if node.msg:
                self._read_edges(node.msg, ctx, fid, node.lineno)
        elif isinstance(node, ast.Raise) and node.exc:
            self._read_edges(node.exc, ctx, fid, node.lineno)
        elif isinstance(node, ast.Try):
            pass
        for child in ast.iter_child_nodes(node):
            if isinstance(child, self._STMT_WALK_TYPES):
                if isinstance(
                    child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
                ):
                    if isinstance(
                        node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
                    ):
                        continue
                self._walk(child, ctx, fid, fnodes, mq)

    def _proc_call(
        self,
        node: ast.Call,
        ctx: list[int],
        fid: int,
        fnodes: dict[str, int],
        mq: str,
    ) -> None:
        """Process a function call."""
        caller = ctx[-1] if ctx[-1] else 0
        cname = self._call_name(node.func)
        cids = self._resolve_symbol(cname)
        if isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Call):
                self._walk(node.func.value, ctx, fid, fnodes, mq)
            oname = self._call_name(node.func.value)
            for oid in self._resolve_symbol(oname):
                if caller != oid:
                    self.add_edge(caller, oid, "read", fid, node.lineno)
                for cid in cids:
                    self.add_edge(oid, cid, "call", fid, node.lineno)
        for cid in cids:
            if cid != caller:
                self.add_edge(caller, cid, "call", fid, node.lineno)
        if not cids and isinstance(node.func, ast.Attribute):
            cur_attr: ast.expr = node.func
            while isinstance(cur_attr, ast.Attribute):
                cur_attr = cur_attr.value
            if isinstance(cur_attr, ast.Name):
                leaf_cids = self._resolve_symbol(node.func.attr)
                for cid in leaf_cids:
                    if cid != caller:
                        self.add_edge(caller, cid, "call", fid, node.lineno)
        for arg in node.args:
            if isinstance(arg, ast.Call):
                self._walk(arg, ctx, fid, fnodes, mq)
            else:
                self._read_edges(arg, ctx, fid, node.lineno)
        for kw in node.keywords:
            if isinstance(kw.value, ast.Call):
                self._walk(kw.value, ctx, fid, fnodes, mq)
            else:
                self._read_edges(kw.value, ctx, fid, node.lineno)

    def _proc_assign(
        self,
        node: ast.Assign,
        ctx: list[int],
        fid: int,
        fnodes: dict[str, int],
        mq: str,
    ) -> None:
        """Process an assignment statement."""
        caller = ctx[-1] if ctx[-1] else 0
        scope = (
            self._node_id_map.get(caller, NodeInfo()).qualified_name if caller else mq
        )
        for t in node.targets:
            for tid in self._target_ids(t, scope):
                if tid != caller:
                    self.add_edge(caller, tid, "write", fid, node.lineno)
            self._read_target_expr(t, ctx, fid, node.lineno)
        if isinstance(node.value, ast.Call):
            self._walk(node.value, ctx, fid, fnodes, mq)
        else:
            self._read_edges(node.value, ctx, fid, node.lineno)

    def _proc_annassign(
        self,
        node: ast.AnnAssign,
        ctx: list[int],
        fid: int,
        mq: str = "",
    ) -> None:
        """Process an annotated assignment."""
        if node.target:
            caller = ctx[-1] if ctx[-1] else 0
            scope = (
                self._node_id_map.get(caller, NodeInfo()).qualified_name
                if caller
                else mq
            )
            for tid in self._target_ids(node.target, scope):
                if tid != caller:
                    self.add_edge(caller, tid, "write", fid, node.lineno)
        if node.value:
            self._read_edges(node.value, ctx, fid, node.lineno)

    def _read_edges(
        self,
        expr: ast.AST,
        ctx: list[int],
        fid: int,
        line: int,
    ) -> None:
        """Recursively collect READ edges from all expressions."""
        caller = ctx[-1] if ctx[-1] else 0
        scope = (
            self._node_id_map.get(caller, NodeInfo()).qualified_name if caller else ""
        )
        if isinstance(expr, ast.Name) and isinstance(expr.ctx, ast.Load):
            for tid in self._resolve_symbol(expr.id, scope):
                if tid != caller:
                    self.add_edge(caller, tid, "read", fid, line)
        elif isinstance(expr, ast.Attribute):
            self._read_edges(expr.value, ctx, fid, line)
            for tid in self._resolve_symbol(expr.attr, scope):
                if tid != caller:
                    self.add_edge(caller, tid, "read", fid, line)
        elif isinstance(expr, ast.Call):
            self._read_edges(expr.func, ctx, fid, line)
            cname = self._call_name(expr.func)
            cids = self._resolve_symbol(cname)
            for cid in cids:
                if cid != caller:
                    self.add_edge(caller, cid, "call", fid, line)
            for a in expr.args:
                self._read_edges(a, ctx, fid, line)
            for kw in expr.keywords:
                self._read_edges(kw.value, ctx, fid, line)
        elif isinstance(expr, ast.Subscript):
            self._read_edges(expr.value, ctx, fid, line)
            self._read_edges(expr.slice, ctx, fid, line)
        elif isinstance(expr, ast.BinOp):
            self._read_edges(expr.left, ctx, fid, line)
            self._read_edges(expr.right, ctx, fid, line)
        elif isinstance(expr, ast.Compare):
            self._read_edges(expr.left, ctx, fid, line)
            for c in expr.comparators:
                self._read_edges(c, ctx, fid, line)
        elif isinstance(expr, ast.UnaryOp):
            self._read_edges(expr.operand, ctx, fid, line)
        elif isinstance(expr, ast.BoolOp):
            for v in expr.values:
                self._read_edges(v, ctx, fid, line)
        elif isinstance(expr, (ast.List, ast.Tuple, ast.Set)):
            for e in expr.elts:
                self._read_edges(e, ctx, fid, line)
        elif isinstance(expr, ast.Dict):
            for k, v in zip(expr.keys or [], expr.values):
                if k:
                    self._read_edges(k, ctx, fid, line)
                self._read_edges(v, ctx, fid, line)
        elif isinstance(expr, ast.JoinedStr):
            for v in expr.values:
                if isinstance(v, ast.FormattedValue):
                    self._read_edges(v.value, ctx, fid, line)
                    if v.format_spec:
                        self._read_edges(v.format_spec, ctx, fid, line)
        elif isinstance(expr, ast.Starred):
            self._read_edges(expr.value, ctx, fid, line)
        elif isinstance(expr, ast.IfExp):
            self._read_edges(expr.test, ctx, fid, line)
            self._read_edges(expr.body, ctx, fid, line)
            self._read_edges(expr.orelse, ctx, fid, line)
        elif isinstance(expr, ast.Lambda):
            self._read_edges(expr.body, ctx, fid, line)
        elif isinstance(expr, ast.GeneratorExp):
            for g in expr.generators:
                self._read_edges(g.iter, ctx, fid, line)
                for i in g.ifs:
                    self._read_edges(i, ctx, fid, line)
            self._read_edges(expr.elt, ctx, fid, line)
        elif isinstance(expr, (ast.ListComp, ast.SetComp)):
            for g in expr.generators:
                self._read_edges(g.iter, ctx, fid, line)
                for i in g.ifs:
                    self._read_edges(i, ctx, fid, line)
            self._read_edges(expr.elt, ctx, fid, line)
        elif isinstance(expr, ast.DictComp):
            for g in expr.generators:
                self._read_edges(g.iter, ctx, fid, line)
                for i in g.ifs:
                    self._read_edges(i, ctx, fid, line)
            self._read_edges(expr.key, ctx, fid, line)
            self._read_edges(expr.value, ctx, fid, line)
        elif isinstance(expr, ast.NamedExpr):
            self._read_edges(expr.value, ctx, fid, line)

    def _resolve_symbol(self, qname: str, scope: str = "") -> list[int]:
        """Resolve a symbol by exact match first, then short name suffix match."""
        if qname in self._symbol_index:
            return list(self._symbol_index[qname])
        r: list[int] = []
        if "." not in qname and qname in self._short_name_index:
            ids = list(self._short_name_index[qname])
            if scope and len(ids) > 1:
                scoped = [
                    i
                    for i in ids
                    if self._node_id_map.get(i, NodeInfo()).qualified_name.startswith(
                        scope
                    )
                ]
                if scoped:
                    return scoped
            return ids
        for qn, ids in self._symbol_index.items():
            if qn.endswith(f".{qname}") or qn == qname:
                r.extend(ids)
        return r

    @staticmethod
    def _call_name(func: ast.expr) -> str:
        if isinstance(func, ast.Name):
            return func.id
        if isinstance(func, ast.Attribute):
            parts = [func.attr]
            cur = func.value
            while isinstance(cur, ast.Attribute):
                parts.append(cur.attr)
                cur = cur.value
            if isinstance(cur, ast.Name) and cur.id != "self":
                parts.append(cur.id)
            parts.reverse()
            return ".".join(parts)
        return ""

    def _target_ids(self, target: ast.expr, scope: str = "") -> list[int]:
        if isinstance(target, ast.Name):
            return self._resolve_symbol(target.id, scope)
        if isinstance(target, ast.Attribute):
            if isinstance(target.value, ast.Attribute):
                return []
            return self._resolve_symbol(target.attr, scope)
        if isinstance(target, (ast.Tuple, ast.List)):
            ids: list[int] = []
            for e in target.elts:
                ids.extend(self._target_ids(e, scope))
            return ids
        return []

    def _read_target_expr(
        self,
        expr: ast.AST,
        ctx: list[int],
        fid: int,
        line: int,
    ) -> None:
        """Read expressions embedded in assignment targets (e.g., f[call(...)] = v)."""
        if isinstance(expr, ast.Subscript):
            self._read_target_expr(expr.value, ctx, fid, line)
            self._read_target_expr(expr.slice, ctx, fid, line)
        elif isinstance(expr, ast.Attribute):
            self._read_target_expr(expr.value, ctx, fid, line)
        elif isinstance(expr, ast.Call):
            self._read_edges(expr.func, ctx, fid, line)
            for arg in expr.args:
                self._read_edges(arg, ctx, fid, line)
            for kw in expr.keywords:
                self._read_edges(kw.value, ctx, fid, line)

    def _node_id_for(self, node: NodeInfo) -> int:
        for n in self._nodes:
            if (
                n.qualified_name == node.qualified_name
                and n.file_id == node.file_id
                and n.line_start == node.line_start
            ):
                return n.id
        return 0

    def get_all_data(self) -> GraphBuildResult:
        """Return all built data."""
        cm, cs = find_connected_components(
            self._nodes,
            self._edges,
            self._node_id_map,
            [],
            {},
        )
        return GraphBuildResult(
            nodes=list(self._nodes),
            edges=list(self._edges),
            warnings=self.warning_collector.get_all(),
            component_map=cm,
            components=cs,
            node_id_map=dict(self._node_id_map),
        )
