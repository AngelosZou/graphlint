# -*- coding: utf-8 -*-
"""Dependency graph builder — builds directed/undirected edges, detects circular references and connected components."""

from __future__ import annotations

import ast
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
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


# ---------------------------------------------------------------------------
# Module-level AST walk functions — shared by serial and parallel code paths
# ---------------------------------------------------------------------------

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
    ast.ExceptHandler,
)


def _resolve_symbol(
    qname: str,
    scope: str,
    symbol_index: dict[str, list[int]],
    suffix_index: dict[str, list[int]],
    node_id_map: dict[int, NodeInfo],
) -> list[int]:
    """Resolve a symbol by exact match first, then suffix match."""
    if qname in symbol_index:
        return list(symbol_index[qname])
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
                return scoped
        return result
    return []


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


def _read_edges(
    expr: ast.AST,
    ctx: list[int],
    fid: int,
    line: int,
    edges: list[EdgeInfo],
    symbol_index: dict[str, list[int]],
    suffix_index: dict[str, list[int]],
    node_id_map: dict[int, NodeInfo],
    config: dict[str, Any],
) -> None:
    """Recursively collect READ edges from all expressions."""
    caller = ctx[-1] if ctx[-1] else 0
    scope = node_id_map.get(caller, NodeInfo()).qualified_name if caller else ""
    if isinstance(expr, ast.Name) and isinstance(expr.ctx, ast.Load):
        for tid in _resolve_symbol(expr.id, scope, symbol_index, suffix_index, node_id_map):
            if tid != caller:
                edges.append(EdgeInfo(caller, tid, "read", fid, line))
    elif isinstance(expr, ast.Attribute):
        _read_edges(expr.value, ctx, fid, line, edges, symbol_index, suffix_index, node_id_map, config)
        for tid in _resolve_symbol(expr.attr, scope, symbol_index, suffix_index, node_id_map):
            if tid != caller:
                edges.append(EdgeInfo(caller, tid, "read", fid, line))
    elif isinstance(expr, ast.Call):
        _read_edges(expr.func, ctx, fid, line, edges, symbol_index, suffix_index, node_id_map, config)
        cname = _call_name(expr.func)
        cids = _resolve_symbol(cname, "", symbol_index, suffix_index, node_id_map)
        for cid in cids:
            if cid != caller:
                edges.append(EdgeInfo(caller, cid, "call", fid, line))
        for a in expr.args:
            _read_edges(a, ctx, fid, line, edges, symbol_index, suffix_index, node_id_map, config)
        for kw in expr.keywords:
            _read_edges(kw.value, ctx, fid, line, edges, symbol_index, suffix_index, node_id_map, config)
    elif isinstance(expr, ast.Subscript):
        _read_edges(expr.value, ctx, fid, line, edges, symbol_index, suffix_index, node_id_map, config)
        _read_edges(expr.slice, ctx, fid, line, edges, symbol_index, suffix_index, node_id_map, config)
    elif isinstance(expr, ast.BinOp):
        _read_edges(expr.left, ctx, fid, line, edges, symbol_index, suffix_index, node_id_map, config)
        _read_edges(expr.right, ctx, fid, line, edges, symbol_index, suffix_index, node_id_map, config)
    elif isinstance(expr, ast.Compare):
        _read_edges(expr.left, ctx, fid, line, edges, symbol_index, suffix_index, node_id_map, config)
        for c in expr.comparators:
            _read_edges(c, ctx, fid, line, edges, symbol_index, suffix_index, node_id_map, config)
    elif isinstance(expr, ast.UnaryOp):
        _read_edges(expr.operand, ctx, fid, line, edges, symbol_index, suffix_index, node_id_map, config)
    elif isinstance(expr, ast.BoolOp):
        for v in expr.values:
            _read_edges(v, ctx, fid, line, edges, symbol_index, suffix_index, node_id_map, config)
    elif isinstance(expr, (ast.List, ast.Tuple, ast.Set)):
        for e in expr.elts:
            _read_edges(e, ctx, fid, line, edges, symbol_index, suffix_index, node_id_map, config)
    elif isinstance(expr, ast.Dict):
        for k, v in zip(expr.keys or [], expr.values):
            if k:
                _read_edges(k, ctx, fid, line, edges, symbol_index, suffix_index, node_id_map, config)
            _read_edges(v, ctx, fid, line, edges, symbol_index, suffix_index, node_id_map, config)
    elif isinstance(expr, ast.JoinedStr):
        for v in expr.values:
            if isinstance(v, ast.FormattedValue):
                _read_edges(v.value, ctx, fid, line, edges, symbol_index, suffix_index, node_id_map, config)
                if v.format_spec:
                    _read_edges(v.format_spec, ctx, fid, line, edges, symbol_index, suffix_index, node_id_map, config)
    elif isinstance(expr, ast.Starred):
        _read_edges(expr.value, ctx, fid, line, edges, symbol_index, suffix_index, node_id_map, config)
    elif isinstance(expr, ast.IfExp):
        _read_edges(expr.test, ctx, fid, line, edges, symbol_index, suffix_index, node_id_map, config)
        _read_edges(expr.body, ctx, fid, line, edges, symbol_index, suffix_index, node_id_map, config)
        _read_edges(expr.orelse, ctx, fid, line, edges, symbol_index, suffix_index, node_id_map, config)
    elif isinstance(expr, ast.Lambda):
        _read_edges(expr.body, ctx, fid, line, edges, symbol_index, suffix_index, node_id_map, config)
    elif isinstance(expr, ast.GeneratorExp):
        for g in expr.generators:
            _read_edges(g.iter, ctx, fid, line, edges, symbol_index, suffix_index, node_id_map, config)
            for i in g.ifs:
                _read_edges(i, ctx, fid, line, edges, symbol_index, suffix_index, node_id_map, config)
        _read_edges(expr.elt, ctx, fid, line, edges, symbol_index, suffix_index, node_id_map, config)
    elif isinstance(expr, (ast.ListComp, ast.SetComp)):
        for g in expr.generators:
            _read_edges(g.iter, ctx, fid, line, edges, symbol_index, suffix_index, node_id_map, config)
            for i in g.ifs:
                _read_edges(i, ctx, fid, line, edges, symbol_index, suffix_index, node_id_map, config)
        _read_edges(expr.elt, ctx, fid, line, edges, symbol_index, suffix_index, node_id_map, config)
    elif isinstance(expr, ast.DictComp):
        for g in expr.generators:
            _read_edges(g.iter, ctx, fid, line, edges, symbol_index, suffix_index, node_id_map, config)
            for i in g.ifs:
                _read_edges(i, ctx, fid, line, edges, symbol_index, suffix_index, node_id_map, config)
        _read_edges(expr.key, ctx, fid, line, edges, symbol_index, suffix_index, node_id_map, config)
        _read_edges(expr.value, ctx, fid, line, edges, symbol_index, suffix_index, node_id_map, config)
    elif isinstance(expr, ast.NamedExpr):
        _read_edges(expr.value, ctx, fid, line, edges, symbol_index, suffix_index, node_id_map, config)


def _target_ids(
    target: ast.expr,
    scope: str,
    symbol_index: dict[str, list[int]],
    suffix_index: dict[str, list[int]],
    node_id_map: dict[int, NodeInfo],
) -> list[int]:
    if isinstance(target, ast.Name):
        return _resolve_symbol(target.id, scope, symbol_index, suffix_index, node_id_map)
    if isinstance(target, ast.Attribute):
        if isinstance(target.value, ast.Attribute):
            return []
        return _resolve_symbol(target.attr, scope, symbol_index, suffix_index, node_id_map)
    if isinstance(target, (ast.Tuple, ast.List)):
        ids: list[int] = []
        for e in target.elts:
            ids.extend(_target_ids(e, scope, symbol_index, suffix_index, node_id_map))
        return ids
    return []


def _read_target_expr(
    expr: ast.AST,
    ctx: list[int],
    fid: int,
    line: int,
    edges: list[EdgeInfo],
    symbol_index: dict[str, list[int]],
    suffix_index: dict[str, list[int]],
    node_id_map: dict[int, NodeInfo],
    config: dict[str, Any],
) -> None:
    """Read expressions embedded in assignment targets (e.g., f[call(...)] = v)."""
    if isinstance(expr, ast.Subscript):
        _read_target_expr(expr.value, ctx, fid, line, edges, symbol_index, suffix_index, node_id_map, config)
        _read_target_expr(expr.slice, ctx, fid, line, edges, symbol_index, suffix_index, node_id_map, config)
    elif isinstance(expr, ast.Attribute):
        _read_target_expr(expr.value, ctx, fid, line, edges, symbol_index, suffix_index, node_id_map, config)
    elif isinstance(expr, ast.Call):
        _read_edges(expr.func, ctx, fid, line, edges, symbol_index, suffix_index, node_id_map, config)
        for arg in expr.args:
            _read_edges(arg, ctx, fid, line, edges, symbol_index, suffix_index, node_id_map, config)
        for kw in expr.keywords:
            _read_edges(kw.value, ctx, fid, line, edges, symbol_index, suffix_index, node_id_map, config)


def _proc_call(
    node: ast.Call,
    ctx: list[int],
    fid: int,
    fnodes: dict[str, int],
    mq: str,
    edges: list[EdgeInfo],
    symbol_index: dict[str, list[int]],
    suffix_index: dict[str, list[int]],
    node_id_map: dict[int, NodeInfo],
    config: dict[str, Any],
) -> None:
    """Process a function call."""
    caller = ctx[-1] if ctx[-1] else 0
    cname = _call_name(node.func)
    cids = _resolve_symbol(cname, "", symbol_index, suffix_index, node_id_map)
    if isinstance(node.func, ast.Attribute):
        if isinstance(node.func.value, ast.Call):
            _walk(node.func.value, ctx, fid, fnodes, mq, edges, symbol_index, suffix_index, node_id_map, config)
        oname = _call_name(node.func.value)
        for oid in _resolve_symbol(oname, "", symbol_index, suffix_index, node_id_map):
            if caller != oid:
                edges.append(EdgeInfo(caller, oid, "read", fid, node.lineno))
            for cid in cids:
                edges.append(EdgeInfo(oid, cid, "call", fid, node.lineno))
    for cid in cids:
        if cid != caller:
            edges.append(EdgeInfo(caller, cid, "call", fid, node.lineno))
    if not cids and isinstance(node.func, ast.Attribute):
        cur_attr: ast.expr = node.func
        while isinstance(cur_attr, ast.Attribute):
            cur_attr = cur_attr.value
        if isinstance(cur_attr, ast.Name):
            leaf_cids = _resolve_symbol(node.func.attr, "", symbol_index, suffix_index, node_id_map)
            for cid in leaf_cids:
                if cid != caller:
                    edges.append(EdgeInfo(caller, cid, "call", fid, node.lineno))
    for arg in node.args:
        if isinstance(arg, ast.Call):
            _walk(arg, ctx, fid, fnodes, mq, edges, symbol_index, suffix_index, node_id_map, config)
        else:
            _read_edges(arg, ctx, fid, node.lineno, edges, symbol_index, suffix_index, node_id_map, config)
    for kw in node.keywords:
        if isinstance(kw.value, ast.Call):
            _walk(kw.value, ctx, fid, fnodes, mq, edges, symbol_index, suffix_index, node_id_map, config)
        else:
            _read_edges(kw.value, ctx, fid, node.lineno, edges, symbol_index, suffix_index, node_id_map, config)


def _proc_assign(
    node: ast.Assign,
    ctx: list[int],
    fid: int,
    fnodes: dict[str, int],
    mq: str,
    edges: list[EdgeInfo],
    symbol_index: dict[str, list[int]],
    suffix_index: dict[str, list[int]],
    node_id_map: dict[int, NodeInfo],
    config: dict[str, Any],
) -> None:
    """Process an assignment statement."""
    caller = ctx[-1] if ctx[-1] else 0
    scope = node_id_map.get(caller, NodeInfo()).qualified_name if caller else mq
    for t in node.targets:
        for tid in _target_ids(t, scope, symbol_index, suffix_index, node_id_map):
            if tid != caller:
                edges.append(EdgeInfo(caller, tid, "write", fid, node.lineno))
        _read_target_expr(t, ctx, fid, node.lineno, edges, symbol_index, suffix_index, node_id_map, config)
    if isinstance(node.value, ast.Call):
        _walk(node.value, ctx, fid, fnodes, mq, edges, symbol_index, suffix_index, node_id_map, config)
    else:
        _read_edges(node.value, ctx, fid, node.lineno, edges, symbol_index, suffix_index, node_id_map, config)


def _proc_annassign(
    node: ast.AnnAssign,
    ctx: list[int],
    fid: int,
    mq: str,
    edges: list[EdgeInfo],
    symbol_index: dict[str, list[int]],
    suffix_index: dict[str, list[int]],
    node_id_map: dict[int, NodeInfo],
    config: dict[str, Any],
) -> None:
    """Process an annotated assignment."""
    if node.target:
        caller = ctx[-1] if ctx[-1] else 0
        scope = node_id_map.get(caller, NodeInfo()).qualified_name if caller else mq
        for tid in _target_ids(node.target, scope, symbol_index, suffix_index, node_id_map):
            if tid != caller:
                edges.append(EdgeInfo(caller, tid, "write", fid, node.lineno))
    if node.value:
        _read_edges(node.value, ctx, fid, node.lineno, edges, symbol_index, suffix_index, node_id_map, config)


def _walk(
    node: ast.AST,
    ctx: list[int],
    fid: int,
    fnodes: dict[str, int],
    mq: str,
    edges: list[EdgeInfo],
    symbol_index: dict[str, list[int]],
    suffix_index: dict[str, list[int]],
    node_id_map: dict[int, NodeInfo],
    config: dict[str, Any],
) -> None:
    """Recursively walk AST to build edges."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        nid = fnodes.get(f"{mq}.{node.name}", 0)
        ctx.append(nid)
        for dec in node.decorator_list:
            dec_name = _call_name(
                dec.func if isinstance(dec, ast.Call) else dec
            )
            dec_ids = _resolve_symbol(dec_name, "", symbol_index, suffix_index, node_id_map)
            for did in dec_ids:
                if did != nid:
                    edges.append(EdgeInfo(nid, did, "decorate", fid, node.lineno))
        for item in node.body:
            _walk(item, ctx, fid, fnodes, mq, edges, symbol_index, suffix_index, node_id_map, config)
        ctx.pop()
    elif isinstance(node, ast.ClassDef):
        nid = fnodes.get(f"{mq}.{node.name}", 0)
        ctx.append(nid)
        old_mq = mq
        mq = f"{mq}.{node.name}"
        for base in node.bases:
            base_name = _call_name(base)
            base_ids = _resolve_symbol(base_name, "", symbol_index, suffix_index, node_id_map)
            for bid in base_ids:
                if bid != nid:
                    edges.append(EdgeInfo(nid, bid, "inherit", fid, node.lineno))
        for dec in node.decorator_list:
            dec_name = _call_name(
                dec.func if isinstance(dec, ast.Call) else dec
            )
            dec_ids = _resolve_symbol(dec_name, "", symbol_index, suffix_index, node_id_map)
            for did in dec_ids:
                if did != nid:
                    edges.append(EdgeInfo(nid, did, "decorate", fid, node.lineno))
        for item in node.body:
            _walk(item, ctx, fid, fnodes, mq, edges, symbol_index, suffix_index, node_id_map, config)
        mq = old_mq
        ctx.pop()
    elif isinstance(node, ast.Call):
        _proc_call(node, ctx, fid, fnodes, mq, edges, symbol_index, suffix_index, node_id_map, config)
    elif isinstance(node, ast.Assign):
        _proc_assign(node, ctx, fid, fnodes, mq, edges, symbol_index, suffix_index, node_id_map, config)
    elif isinstance(node, ast.AnnAssign):
        _proc_annassign(node, ctx, fid, mq, edges, symbol_index, suffix_index, node_id_map, config)
    elif isinstance(node, ast.Expr):
        _read_edges(node.value, ctx, fid, node.lineno, edges, symbol_index, suffix_index, node_id_map, config)
    elif isinstance(node, ast.Return) and node.value:
        if isinstance(node.value, ast.Call):
            _walk(node.value, ctx, fid, fnodes, mq, edges, symbol_index, suffix_index, node_id_map, config)
        else:
            _read_edges(node.value, ctx, fid, node.lineno, edges, symbol_index, suffix_index, node_id_map, config)
    elif isinstance(node, ast.Raise) and node.exc:
        if isinstance(node.exc, ast.Call):
            _walk(node.exc, ctx, fid, fnodes, mq, edges, symbol_index, suffix_index, node_id_map, config)
        else:
            _read_edges(node.exc, ctx, fid, node.lineno, edges, symbol_index, suffix_index, node_id_map, config)
    elif isinstance(node, (ast.If, ast.While)):
        _read_edges(node.test, ctx, fid, node.lineno, edges, symbol_index, suffix_index, node_id_map, config)
    elif isinstance(node, ast.For):
        _read_edges(node.iter, ctx, fid, node.lineno, edges, symbol_index, suffix_index, node_id_map, config)
    elif isinstance(node, ast.With):
        for item in node.items:
            _read_edges(item.context_expr, ctx, fid, node.lineno, edges, symbol_index, suffix_index, node_id_map, config)
    elif isinstance(node, ast.AugAssign):
        _read_edges(node.value, ctx, fid, node.lineno, edges, symbol_index, suffix_index, node_id_map, config)
    elif isinstance(node, ast.Assert):
        _read_edges(node.test, ctx, fid, node.lineno, edges, symbol_index, suffix_index, node_id_map, config)
        if node.msg:
            _read_edges(node.msg, ctx, fid, node.lineno, edges, symbol_index, suffix_index, node_id_map, config)
    elif isinstance(node, ast.Raise) and node.exc:
        _read_edges(node.exc, ctx, fid, node.lineno, edges, symbol_index, suffix_index, node_id_map, config)
    elif isinstance(node, ast.Try):
        pass
    for child in ast.iter_child_nodes(node):
        if isinstance(child, _STMT_WALK_TYPES):
            if isinstance(
                child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            ):
                if isinstance(
                    node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
                ):
                    continue
            _walk(child, ctx, fid, fnodes, mq, edges, symbol_index, suffix_index, node_id_map, config)


def _build_file_edges_worker(
    fp: str,
    source: str,
    fnodes: dict[str, int],
    fid: int,
    symbol_index: dict[str, list[int]],
    suffix_index: dict[str, list[int]],
    node_id_map: dict[int, NodeInfo],
    config: dict[str, Any],
) -> list[EdgeInfo]:
    """Build edges for a single file — usable from ThreadPoolExecutor."""
    try:
        tree = ast.parse(source, filename=fp)
    except SyntaxError:
        return []
    mq = fp.replace("/", ".").replace(".py", "")
    edges: list[EdgeInfo] = []
    _walk(tree, [0], fid, fnodes, mq, edges, symbol_index, suffix_index, node_id_map, config)
    return edges


# ---------------------------------------------------------------------------
# GraphBuilder
# ---------------------------------------------------------------------------


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
        self._suffix_index: dict[str, list[int]] = {}
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
            parts = qname.split(".")
            for i in range(len(parts)):
                suffix = ".".join(parts[i:])
                self._suffix_index.setdefault(suffix, []).append(nid)
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

        # Parallel edge building for changed files
        pw = self.config.get("performance", {}).get("parallel_workers", 0) or 0
        if pw > 1 and len(changed_list) > 1:
            with ThreadPoolExecutor(max_workers=min(pw, len(changed_list))) as ex:
                futs = {}
                for fp in changed_list:
                    pr = parse_results[fp]
                    fnodes = fnodes_map.get(fp, {})
                    source = pr.source
                    if source is None:
                        abs_p = os.path.join(self.config.get("_root_dir", os.getcwd()), fp)
                        try:
                            with open(abs_p, "r", encoding="utf-8") as fh:
                                source = fh.read()
                        except OSError:
                            continue
                    futs[
                        ex.submit(
                            _build_file_edges_worker,
                            fp, source, fnodes, fid_map[fp],
                            self._symbol_index, self._suffix_index,
                            self._node_id_map, self.config,
                        )
                    ] = fp
                for fut in as_completed(futs):
                    fp = futs[fut]
                    try:
                        self._edges.extend(fut.result())
                    except Exception:
                        pass
        else:
            for fp in changed_list:
                self._build_edges(fp, parse_results[fp], fid_map.get(fp, 0), fnodes_map.get(fp, {}))

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

    # ------------------------------------------------------------------
    # Edge building (delegates to module-level functions)
    # ------------------------------------------------------------------

    def _build_edges(
        self,
        fp: str,
        pr: ParseResult,
        fid: int,
        fnodes: dict[str, int] | None = None,
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
        if fnodes is None:
            fnodes = {}
            for n in self._nodes:
                if n.file_id == fid:
                    fnodes[n.qualified_name] = n.id
        self._edges.extend(
            _build_file_edges_worker(
                fp, src, fnodes, fid,
                self._symbol_index, self._suffix_index,
                self._node_id_map, self.config,
            )
        )

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
