# -*- coding: utf-8 -*-
"""AST visitor — traverses AST to extract nodes, imports, and name usages."""

from __future__ import annotations

import ast
from typing import List, Set

from graphlint.analyzer._types import NodeInfo
from graphlint.analyzer.decorators import DecoratorResolver
from graphlint.analyzer.imports import ImportAnalyzer, ImportInfo


class ASTVisitor(ast.NodeVisitor):
    """Custom AST visitor that extracts nodes, imports, and name usages."""

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

        self._context: List[str] = [module_qualified]
        self._current_class_id: int = 0
        self._current_func_id: int = 0
        self._node_id: int = 1

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
        """Generic visit: collect name usages."""
        if isinstance(node, ast.Name):
            if isinstance(node.ctx, ast.Load):
                self.name_usages.add(node.id)
        elif isinstance(node, ast.Attribute):
            self.name_usages.add(node.attr)
            if isinstance(node.value, ast.Name):
                self.name_usages.add(node.value.id)
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
        self._current_class_id = class_node_id
        self._context.append(node.name)

        for base in node.bases:
            self.visit(base)
        for dec in node.decorator_list:
            self.visit(dec)
        for item in node.body:
            self.visit(item)

        self._context.pop()
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
            self.visit(dec)
        if node.returns:
            self.visit(node.returns)
        if hasattr(node, "args") and isinstance(node.args, ast.arguments):
            for arg in ast.iter_child_nodes(node.args):
                self.visit(arg)

        prev_class_id = self._current_class_id
        prev_func_id = self._current_func_id
        self._current_class_id = 0
        self._current_func_id = func_node_id
        self._context.append(node.name)
        for item in node.body:
            self.visit(item)
        self._context.pop()
        self._current_class_id = prev_class_id
        self._current_func_id = prev_func_id

    # ------------------------------------------------------------------
    # Variable / field
    # ------------------------------------------------------------------

    def visit_Assign(self, node: ast.Assign) -> None:
        """Process assignment statements (module-level or class fields)."""
        is_class_level = self._current_class_id != 0
        is_func_level = not is_class_level and self._current_func_id != 0
        node_type = "field" if is_class_level else "variable"
        if is_class_level:
            parent_id = self._current_class_id
        elif is_func_level:
            parent_id = self._current_func_id
        else:
            parent_id = 0

        for target in node.targets:
            self._extract_target(target, node_type, parent_id, node)

        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        """Process annotated assignment statements."""
        if node.target is None:
            self.generic_visit(node)
            return

        is_class_level = self._current_class_id != 0
        is_func_level = not is_class_level and self._current_func_id != 0
        node_type = "field" if is_class_level else "variable"
        if is_class_level:
            parent_id = self._current_class_id
        elif is_func_level:
            parent_id = self._current_func_id
        else:
            parent_id = 0

        type_ann = ""
        if node.annotation:
            try:
                type_ann = ast.unparse(node.annotation)
            except Exception:
                type_ann = ""
            self.visit(node.annotation)

        self._extract_annotated_target(
            node.target, node_type, parent_id, node, type_ann
        )
        self.generic_visit(node)

    # ------------------------------------------------------------------
    # Target extraction helpers
    # ------------------------------------------------------------------

    def _extract_target(
        self,
        target: ast.expr,
        node_type: str,
        parent_id: int,
        assign_node: ast.Assign,
    ) -> None:
        """Extract variable/field nodes from assignment targets."""
        if isinstance(target, ast.Name):
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
        """Add a node and return its ID."""
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
