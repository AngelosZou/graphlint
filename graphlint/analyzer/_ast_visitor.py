# -*- coding: utf-8 -*-
"""AST visitor — traverses AST to extract nodes, imports, and symbol references."""

from __future__ import annotations

import ast
from typing import List, Set

from graphlint.analyzer._types import NodeInfo, ReferenceInfo
from graphlint.analyzer.decorators import DecoratorResolver
from graphlint.analyzer.imports import ImportAnalyzer, ImportInfo


def _call_name(func: ast.expr) -> str:
    """Extract the dotted name from a function-call expression."""
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


class ASTVisitor(ast.NodeVisitor):
    """Custom AST visitor that extracts nodes, imports, and structured references."""

    def __init__(
        self,
        module_qualified: str,
        file_path: str,
        import_analyzer: ImportAnalyzer,
        decorator_resolver: DecoratorResolver,
    ) -> None:
        """Initialize the AST visitor."""
        super().__init__()
        self.module_qualified: str = module_qualified
        self.file_path: str = file_path
        self.import_analyzer: ImportAnalyzer = import_analyzer
        self.decorator_resolver: DecoratorResolver = decorator_resolver

        self.nodes: List[NodeInfo] = []
        self.imports: List[ImportInfo] = []
        self.name_usages: Set[str] = set()
        self.references: List[ReferenceInfo] = []

        self._context: List[str] = [module_qualified]
        self._class_qualified: str = ""
        self._current_class_id: int = 0
        self._current_func_id: int = 0
        self._node_id: int = 1
        self._global_names: Set[str] = set()
        self._field_qnames: Set[str] = set()

    # ------------------------------------------------------------------
    # Source qualified name at current position
    # ------------------------------------------------------------------

    def _current_qname(self) -> str:
        """Qualified name of the current scope."""
        return ".".join(self._context)

    # ------------------------------------------------------------------
    # Generic visit
    # ------------------------------------------------------------------

    def visit(self, node: ast.AST) -> None:
        """Override visit to gracefully degrade on error."""
        try:
            super().visit(node)
        except Exception as exc:
            import sys

            print(
                f"[graphlint] AST visit error in {self.file_path}: {exc}",
                file=sys.stderr,
            )

    def generic_visit(self, node: ast.AST) -> None:
        """Generic visit: collect read references from all Name/Attribute nodes."""
        sq = self._current_qname()
        if isinstance(node, ast.Name):
            if isinstance(node.ctx, ast.Load):
                target = node.id
                if target in self._global_names:
                    target = self.module_qualified + "." + target
                self.name_usages.add(node.id)
                self.references.append(ReferenceInfo(
                    source_qname=sq,
                    target_name=target,
                    edge_type="read",
                    line=node.lineno or 0,
                ))
        elif isinstance(node, ast.Attribute):
            self.name_usages.add(node.attr)
            if isinstance(node.value, ast.Name):
                self.name_usages.add(node.value.id)
            if isinstance(node.ctx, ast.Load):
                self.references.append(ReferenceInfo(
                    source_qname=sq,
                    target_name=node.attr,
                    edge_type="read",
                    line=node.lineno or 0,
                ))
        super().generic_visit(node)

    # ------------------------------------------------------------------
    # Import visit
    # ------------------------------------------------------------------

    def visit_Import(self, node: ast.Import) -> None:
        """Process import xxx statements."""
        infos = self.import_analyzer.analyze_import(node)
        self.imports.extend(infos)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """Process from xxx import yyy statements."""
        infos = self.import_analyzer.analyze_import(node)
        self.imports.extend(infos)
        self.generic_visit(node)

    # ------------------------------------------------------------------
    # Global declaration
    # ------------------------------------------------------------------

    def visit_Global(self, node: ast.Global) -> None:
        """Process global declaration — names refer to module-level variables."""
        self._global_names.update(node.names)

    # ------------------------------------------------------------------
    # Call
    # ------------------------------------------------------------------

    def visit_Call(self, node: ast.Call) -> None:
        """Emit a call-edge reference and visit the call expression, args, and keywords."""
        sq = self._current_qname()
        cname = _call_name(node.func)
        if cname:
            self.references.append(ReferenceInfo(
                source_qname=sq,
                target_name=cname,
                edge_type="call",
                line=node.lineno or 0,
            ))
        self.visit(node.func)
        for arg in node.args:
            self.visit(arg)
        for kw in node.keywords:
            if kw.value is not None:
                self.visit(kw.value)

    # ------------------------------------------------------------------
    # Class definition
    # ------------------------------------------------------------------

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Process a class definition."""
        qualified = ".".join(self._context + [node.name])
        dec_infos = self.decorator_resolver.extract_decorator_names(
            node.decorator_list, self.module_qualified
        )
        dec_names = [d.qualified_name for d in dec_infos]
        docstring = self._get_docstring(node)
        is_deprecated, dep_msg = DecoratorResolver.check_deprecated(
            node.decorator_list, docstring
        )

        class_node = NodeInfo(
            file_id=0,
            name=node.name,
            qualified_name=qualified,
            node_type="class",
            line_start=node.lineno,
            line_end=node.end_lineno or node.lineno,
            col_offset=node.col_offset,
            parent_node_id=0,
            is_deprecated=is_deprecated,
            deprecation_msg=dep_msg,
            type_annotation="",
            is_async=False,
            decorators=dec_names,
            docstring=docstring,
            is_entry=False,
        )
        class_node_id = self._add_node(class_node)
        prev_class_id = self._current_class_id
        prev_class_qualified = self._class_qualified
        self._current_class_id = class_node_id
        self._class_qualified = qualified
        self._context.append(node.name)

        for base in node.bases:
            base_name = _call_name(base)
            if base_name:
                self.references.append(ReferenceInfo(
                    source_qname=qualified,
                    target_name=base_name,
                    edge_type="inherit",
                    line=base.lineno or node.lineno or 0,
                ))
            self.visit(base)
        for dec in node.decorator_list:
            dec_name = _call_name(
                dec.func if isinstance(dec, ast.Call) else dec
            )
            if dec_name:
                self.references.append(ReferenceInfo(
                    source_qname=qualified,
                    target_name=dec_name,
                    edge_type="decorate",
                    line=dec.lineno or node.lineno or 0,
                ))
            self.visit(dec)
        for item in node.body:
            self.visit(item)

        self._context.pop()
        self._class_qualified = prev_class_qualified
        self._current_class_id = prev_class_id

    # ------------------------------------------------------------------
    # Function definition
    # ------------------------------------------------------------------

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Process a function definition."""
        self._handle_function(node, is_async=False)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Process an async function definition."""
        self._handle_function(node, is_async=True)

    def _handle_function(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef, is_async: bool
    ) -> None:
        """Shared logic for function/method definitions."""
        is_method = self._current_class_id != 0
        qualified = ".".join(self._context + [node.name])
        node_type = "method" if is_method else "function"

        dec_infos = self.decorator_resolver.extract_decorator_names(
            node.decorator_list, self.module_qualified
        )
        dec_names = [d.qualified_name for d in dec_infos]
        docstring = self._get_docstring(node)
        is_deprecated, dep_msg = DecoratorResolver.check_deprecated(
            node.decorator_list, docstring
        )

        type_ann = ""
        if node.returns:
            try:
                type_ann = ast.unparse(node.returns)
            except Exception:
                type_ann = ""

        func_node = NodeInfo(
            file_id=0,
            name=node.name,
            qualified_name=qualified,
            node_type=node_type,
            line_start=node.lineno,
            line_end=node.end_lineno or node.lineno,
            col_offset=node.col_offset,
            parent_node_id=self._current_class_id,
            is_deprecated=is_deprecated,
            deprecation_msg=dep_msg,
            type_annotation=type_ann,
            is_async=is_async,
            decorators=dec_names,
            docstring=docstring,
            is_entry=False,
        )
        func_node_id = self._add_node(func_node)

        for dec in node.decorator_list:
            dec_name = _call_name(
                dec.func if isinstance(dec, ast.Call) else dec
            )
            if dec_name:
                self.references.append(ReferenceInfo(
                    source_qname=qualified,
                    target_name=dec_name,
                    edge_type="decorate",
                    line=dec.lineno or node.lineno or 0,
                ))
            self.visit(dec)
        if node.returns:
            self.visit(node.returns)
        if hasattr(node, "args") and isinstance(node.args, ast.arguments):
            for arg in ast.iter_child_nodes(node.args):
                self.visit(arg)

        prev_class_id = self._current_class_id
        prev_func_id = self._current_func_id
        prev_global_names = self._global_names
        self._current_func_id = func_node_id
        self._global_names = set()
        self._context.append(node.name)
        for item in node.body:
            self.visit(item)
        self._context.pop()
        self._global_names = prev_global_names
        self._current_class_id = prev_class_id
        self._current_func_id = prev_func_id

    # ------------------------------------------------------------------
    # Variable / field
    # ------------------------------------------------------------------

    def _resolve_target_context(self, target: ast.expr) -> tuple[int, str]:
        """Determine parent_id and node_type for an assignment target.

        - ``self.xxx`` / ``cls.xxx`` targets inside a class → field of the class
        - plain ``Name`` targets at class body level → field of the class
        - plain ``Name`` targets inside a method → local variable of the method
        - plain ``Name`` targets at module level → module variable
        """
        has_class = self._current_class_id != 0
        has_func = self._current_func_id != 0

        if isinstance(target, ast.Attribute) and has_class:
            return self._current_class_id, "field"
        if isinstance(target, ast.Name):
            if has_class and not has_func:
                return self._current_class_id, "field"
            if has_func:
                return self._current_func_id, "variable"
            return 0, "variable"
        if isinstance(target, (ast.Tuple, ast.List)):
            for elt in target.elts:
                if isinstance(elt, ast.Attribute) and has_class:
                    return self._current_class_id, "field"
            if has_class and not has_func:
                return self._current_class_id, "field"
            if has_func:
                return self._current_func_id, "variable"
            return 0, "variable"
        return 0, "variable"

    def visit_Assign(self, node: ast.Assign) -> None:
        """Emit write references and extract variable/field nodes from targets."""
        sq = self._current_qname()
        for target in node.targets:
            parent_id, node_type = self._resolve_target_context(target)
            if parent_id != 0:
                self._add_write_ref(target, sq, node.lineno or 0)
            self._extract_target(target, node_type, parent_id, node)
            self._visit_target_subexpr(target)

        self.visit(node.value)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        """Emit write references and extract annotated variable/field nodes."""
        if node.target is None:
            self.generic_visit(node)
            return

        parent_id, node_type = self._resolve_target_context(node.target)

        type_ann = ""
        if node.annotation:
            try:
                type_ann = ast.unparse(node.annotation)
            except Exception:
                type_ann = ""
            self.visit(node.annotation)

        sq = self._current_qname()
        if isinstance(node.target, ast.Name):
            if node.target.id in self._global_names:
                if parent_id != 0:
                    module_target = self.module_qualified + "." + node.target.id
                    self.references.append(ReferenceInfo(
                        source_qname=sq,
                        target_name=module_target,
                        edge_type="write",
                        line=node.lineno or 0,
                    ))
            else:
                if parent_id != 0:
                    self.references.append(ReferenceInfo(
                        source_qname=sq,
                        target_name=node.target.id,
                        edge_type="write",
                        line=node.lineno or 0,
                    ))
                self._extract_annotated_target(
                    node.target, node_type, parent_id, node, type_ann
                )
        elif isinstance(node.target, ast.Attribute) and not isinstance(node.target.value, ast.Attribute):
            if parent_id != 0:
                self.references.append(ReferenceInfo(
                    source_qname=sq,
                    target_name=node.target.attr,
                    edge_type="write",
                    line=node.lineno or 0,
                ))
            self._extract_annotated_target(
                node.target, node_type, parent_id, node, type_ann
            )
        else:
            self._extract_annotated_target(
                node.target, node_type, parent_id, node, type_ann
            )
        if node.value:
            self.visit(node.value)

    # ------------------------------------------------------------------
    # Augmented assignment
    # ------------------------------------------------------------------

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        """Process augmented assignment (e.g. X += 1) — both read and write."""
        sq = self._current_qname()
        if isinstance(node.target, ast.Name):
            target_name = node.target.id
            if target_name in self._global_names:
                module_target = self.module_qualified + "." + target_name
                self.references.append(ReferenceInfo(
                    source_qname=sq,
                    target_name=module_target,
                    edge_type="write",
                    line=node.lineno or 0,
                ))
                self.references.append(ReferenceInfo(
                    source_qname=sq,
                    target_name=module_target,
                    edge_type="read",
                    line=node.lineno or 0,
                ))
            else:
                self.references.append(ReferenceInfo(
                    source_qname=sq,
                    target_name=target_name,
                    edge_type="write",
                    line=node.lineno or 0,
                ))
                self.references.append(ReferenceInfo(
                    source_qname=sq,
                    target_name=target_name,
                    edge_type="read",
                    line=node.lineno or 0,
                ))
            self.name_usages.add(target_name)
        elif isinstance(node.target, ast.Attribute):
            self.references.append(ReferenceInfo(
                source_qname=sq,
                target_name=node.target.attr,
                edge_type="write",
                line=node.lineno or 0,
            ))
            self.references.append(ReferenceInfo(
                source_qname=sq,
                target_name=node.target.attr,
                edge_type="read",
                line=node.lineno or 0,
            ))
            self.name_usages.add(node.target.attr)
            self.visit(node.target.value)
        self.visit(node.value)

    # ------------------------------------------------------------------
    # Write reference helpers (recursive for nested tuples in assignment targets)
    # ------------------------------------------------------------------

    def _add_write_ref(self, target: ast.expr, source_qname: str, line: int) -> None:
        """Add write references for assignment targets, recursing into Tuple/List."""
        if isinstance(target, ast.Name):
            if target.id in self._global_names:
                module_target = self.module_qualified + "." + target.id
                self.references.append(ReferenceInfo(
                    source_qname=source_qname,
                    target_name=module_target,
                    edge_type="write",
                    line=line,
                ))
                return
            self.references.append(ReferenceInfo(
                source_qname=source_qname,
                target_name=target.id,
                edge_type="write",
                line=line,
            ))
        elif isinstance(target, ast.Attribute) and not isinstance(target.value, ast.Attribute):
            self.references.append(ReferenceInfo(
                source_qname=source_qname,
                target_name=target.attr,
                edge_type="write",
                line=line,
            ))
        elif isinstance(target, (ast.Tuple, ast.List)):
            for elt in target.elts:
                self._add_write_ref(elt, source_qname, line)

    # ------------------------------------------------------------------
    # Target extraction helpers
    # ------------------------------------------------------------------

    def _visit_target_subexpr(self, target: ast.expr) -> None:
        """Visit sub-expressions in assignment targets to collect name usages."""
        if isinstance(target, ast.Subscript):
            self.visit(target.value)
            if isinstance(target.slice, ast.expr):
                self.visit(target.slice)
            elif isinstance(target.slice, ast.Tuple):
                for elt in target.slice.elts:
                    if isinstance(elt, ast.expr):
                        self.visit(elt)
        elif isinstance(target, ast.Attribute):
            self.visit(target.value)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for elt in target.elts:
                self._visit_target_subexpr(elt)

    def _extract_target(
        self,
        target: ast.expr,
        node_type: str,
        parent_id: int,
        assign_node: ast.Assign,
    ) -> None:
        """Extract variable/field nodes from assignment targets."""
        if isinstance(target, ast.Name):
            if target.id in self._global_names:
                return
            qualified = ".".join(self._context + [target.id])
            self._add_node(
                NodeInfo(
                    file_id=0,
                    name=target.id,
                    qualified_name=qualified,
                    node_type=node_type,
                    line_start=assign_node.lineno,
                    line_end=assign_node.end_lineno or assign_node.lineno,
                    col_offset=assign_node.col_offset,
                    parent_node_id=parent_id,
                )
            )
        elif isinstance(target, ast.Attribute):
            if isinstance(target.value, ast.Attribute):
                return
            if node_type == "field" and self._class_qualified:
                qualified = self._class_qualified + "." + target.attr
            else:
                qualified = ".".join(self._context + [target.attr])
            self._add_node(
                NodeInfo(
                    file_id=0,
                    name=target.attr,
                    qualified_name=qualified,
                    node_type=node_type,
                    line_start=assign_node.lineno,
                    line_end=assign_node.end_lineno or assign_node.lineno,
                    col_offset=assign_node.col_offset,
                    parent_node_id=parent_id,
                )
            )
        elif isinstance(target, (ast.Tuple, ast.List)):
            for elt in target.elts:
                self._extract_target(elt, node_type, parent_id, assign_node)

    def _extract_annotated_target(
        self,
        target: ast.expr,
        node_type: str,
        parent_id: int,
        node: ast.AnnAssign,
        type_ann: str,
    ) -> None:
        """Extract nodes from annotated assignment targets."""
        if isinstance(target, ast.Name):
            if target.id in self._global_names:
                return
            qualified = ".".join(self._context + [target.id])
            self._add_node(
                NodeInfo(
                    file_id=0,
                    name=target.id,
                    qualified_name=qualified,
                    node_type=node_type,
                    line_start=node.lineno,
                    line_end=node.end_lineno or node.lineno,
                    col_offset=node.col_offset,
                    parent_node_id=parent_id,
                    type_annotation=type_ann,
                )
            )
        elif isinstance(target, ast.Attribute):
            if isinstance(target.value, ast.Attribute):
                return
            if node_type == "field" and self._class_qualified:
                qualified = self._class_qualified + "." + target.attr
            else:
                qualified = ".".join(self._context + [target.attr])
            self._add_node(
                NodeInfo(
                    file_id=0,
                    name=target.attr,
                    qualified_name=qualified,
                    node_type=node_type,
                    line_start=node.lineno,
                    line_end=node.end_lineno or node.lineno,
                    col_offset=node.col_offset,
                    parent_node_id=parent_id,
                    type_annotation=type_ann,
                )
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _add_node(self, node: NodeInfo) -> int:
        """Add a node and return its ID.

        Field nodes are deduplicated by qualified_name: when the same
        class field is assigned in multiple methods, only the first
        occurrence produces a node (subsequent occurrences are no-ops).
        """
        if node.node_type == "field" and node.qualified_name:
            if node.qualified_name in self._field_qnames:
                return 0
            self._field_qnames.add(node.qualified_name)
        node_id = self._node_id
        self._node_id += 1
        node.id = node_id
        self.nodes.append(node)
        return node_id

    @staticmethod
    def _get_docstring(node: ast.AST) -> str:
        """Extract docstring (truncated to 500 chars)."""
        ds = ast.get_docstring(node) or ""  # type: ignore[arg-type]
        if len(ds) > 500:
            ds = ds[:497] + "..."
        return ds
