# -*- coding: utf-8 -*-
"""Tree-sitter CST visitor — traverses the TS/JS concrete syntax tree to extract
nodes (symbol definitions), structured references (edges), and imports."""

from __future__ import annotations

from typing import Any

from graphlint.analyzer._types import NodeInfo, ReferenceInfo
from graphlint.analyzer.language.typescript.constants import (
    _CST_TYPE_TO_NODE_TYPE,
    _TYPE_MEMBER_NODE_TYPES,
)
from graphlint.analyzer.language.typescript.imports import (
    TSTypeScriptImportAnalyzer,
    ImportInfo,
    ExportInfo,
)
from graphlint.analyzer.warnings import WarningInfo


def _node_text(node: Any) -> str:
    try:
        return node.text.decode("utf-8") if node.text else ""
    except (UnicodeDecodeError, AttributeError):
        return ""


def _node_line(node: Any) -> int:
    try:
        return (node.start_point[0] + 1) if node.start_point else 0
    except (AttributeError, IndexError, TypeError):
        return 0


def _node_end_line(node: Any) -> int:
    try:
        return (node.end_point[0] + 1) if node.end_point else 0
    except (AttributeError, IndexError, TypeError):
        return 0


def _node_col(node: Any) -> int:
    try:
        return node.start_point[1] if node.start_point else 0
    except (AttributeError, IndexError, TypeError):
        return 0


def _scoped_name(node: Any) -> str:
    """Extract dotted name from a member_expression or identifier node."""
    if node.type == "member_expression":
        obj = node.child_by_field_name("object")
        prop = node.child_by_field_name("property")
        obj_name = _scoped_name(obj) if obj else ""
        prop_name = _node_text(prop) if prop else ""
        if obj_name and prop_name:
            return obj_name + "." + prop_name
        return prop_name
    if node.type in ("identifier", "property_identifier"):
        return _node_text(node)
    if node.type == "this" or node.type == "super":
        return _node_text(node)
    return ""


def _call_name_from_expr(expr_node: Any) -> str:
    """Extract the callable name from an expression node."""
    if expr_node.type == "identifier":
        return _node_text(expr_node)
    if expr_node.type == "member_expression":
        prop = expr_node.child_by_field_name("property")
        if prop:
            return _node_text(prop)
    if expr_node.type in ("new_expression",):
        constr = expr_node.child_by_field_name("constructor")
        if constr and constr.type == "identifier":
            return _node_text(constr)
    return ""


def _dotted_call_name(expr_node: Any) -> str:
    """Full dotted name of a callable expression (e.g. ``app.use``)."""
    if expr_node.type == "member_expression":
        obj = expr_node.child_by_field_name("object")
        prop = expr_node.child_by_field_name("property")
        base = _dotted_call_name(obj) if obj else ""
        nm = _node_text(prop) if prop else ""
        if base and nm:
            return base + "." + nm
        return nm
    if expr_node.type == "identifier":
        return _node_text(expr_node)
    return ""


def _generic_base_name(node: Any) -> str:
    """Base name of a generic type reference without type arguments."""
    if node.type == "generic_type":
        name_node = node.child_by_field_name("name") or node.child_by_field_name("type")
        if name_node:
            return _node_text(name_node)
        for child in node.children:
            if child.type == "identifier":
                return _node_text(child)
        return _node_text(node)
    return _node_text(node)


def _extract_decorators(node: Any) -> list[str]:
    """Extract decorator names attached to *node*."""
    names: list[str] = []
    for child in node.children:
        if child.type == "decorator":
            name_node = child.child_by_field_name("name") or child.child_by_field_name(
                "call"
            )
            if name_node is None:
                for c in child.children:
                    if c.type in ("identifier", "call_expression"):
                        name_node = c
                        break
            if name_node is not None:
                dec_name = (
                    _scoped_name(name_node)
                    if name_node.type == "identifier"
                    else (
                        _scoped_name(name_node.child_by_field_name("function"))
                        if name_node.type == "call_expression"
                        and name_node.child_by_field_name("function")
                        else _call_name_from_expr(
                            name_node.child_by_field_name("function")
                        )
                        if name_node.type == "call_expression"
                        else ""
                    )
                )
                if dec_name:
                    names.append(dec_name)
    if names:
        return names

    # Check preceding siblings (older grammar layouts)
    parent = node.parent
    if parent:
        children = list(parent.children)
        node_idx = None
        for i, child in enumerate(children):
            if child == node:
                node_idx = i
                break
        if node_idx is not None:
            for i in range(node_idx - 1, -1, -1):
                child = children[i]
                if child.type == "decorator":
                    for c in child.children:
                        if c.type in ("identifier", "call_expression"):
                            names.append(_scoped_name(c) if c.type == "identifier" else _call_name_from_expr(c.child_by_field_name("function")))
                elif child.type in ("comment",):
                    continue
                else:
                    break
    return names


def _extract_visibility(node: Any) -> str:
    """Extract access modifier from a class member node."""
    for child in node.children:
        if child.type in ("public", "private", "protected", "readonly", "static", "abstract", "async"):
            # In tree-sitter-typescript, modifiers are keyword nodes
            pass  # handled at the class member level
    # Check for access_modifier child
    am = node.child_by_field_name("access_modifier") or node.child_by_field_name("modifier")
    if am:
        return _node_text(am)
    # Check children for modifier nodes
    for child in node.children:
        txt = _node_text(child)
        if txt in ("public", "private", "protected"):
            return txt
    return ""


def _extract_return_type(node: Any) -> str:
    """Extract the return type annotation of a function/method."""
    # TypeScript: return_type child
    rt = node.child_by_field_name("return_type")
    if rt and rt.type == "type_annotation":
        for child in rt.children:
            if child.type != ":":
                return _node_text(child)
    return ""


def _extract_property_type(node: Any) -> str:
    """Extract the type annotation of a property/field."""
    ta = node.child_by_field_name("type_annotation") or node.child_by_field_name("type")
    if ta:
        if ta.type == "type_annotation":
            for child in ta.children:
                if child.type != ":":
                    return _node_text(child)
        return _node_text(ta)
    return ""


def _has_modifier(node: Any, modifier: str) -> bool:
    """Check if node has a specific modifier keyword."""
    for child in node.children:
        txt = _node_text(child)
        if txt == modifier:
            return True
    return False


def _extract_base_types(node: Any) -> list[str]:
    """Extract base class and interface names from a class/interface declaration.

    tree-sitter-typescript nests heritage clauses under named (non-field)
    children:
    - ``class_declaration``: ``class_heritage`` -> ``extends_clause`` /
      ``implements_clause``
    - ``interface_declaration``: ``extends_type_clause``
    """

    bases: list[str] = []

    def _collect_names(clause: Any) -> None:
        for child in clause.children:
            if child.type in (
                "identifier",
                "type_identifier",
                "member_expression",
                "generic_type",
            ):
                name = _scoped_name(child) or _generic_base_name(child)
                if name:
                    bases.append(name)

    heritage = node.child_by_field_name("class_heritage") or node.child_by_field_name("extends")
    if heritage is None:
        heritage = next(
            (c for c in node.children if c.type == "class_heritage"),
            None,
        )

    if heritage is not None:
        for clause in heritage.children:
            if clause.type in ("extends_clause", "implements_clause"):
                _collect_names(clause)

    interface_extends = next(
        (c for c in node.children if c.type == "extends_type_clause"),
        None,
    )
    if interface_extends is not None:
        _collect_names(interface_extends)

    return bases


class TSTypeScriptVisitor:
    """Walks a tree-sitter CST of TypeScript/JavaScript and extracts nodes,
    references, and imports."""

    def __init__(
        self,
        module_qname: str,
        file_path: str,
        import_analyzer: TSTypeScriptImportAnalyzer,
    ) -> None:
        self.module_qname = module_qname
        self.file_path = file_path
        self.import_analyzer = import_analyzer

        self.nodes: list[NodeInfo] = []
        self.references: list[ReferenceInfo] = []
        self.name_usages: set[str] = set()
        self.imports: list[ImportInfo] = []
        self.exports: list[ExportInfo] = []
        self.warnings: list[Any] = []

        self._context: list[str] = []
        self._current_type_id: int = 0
        self._current_type_qname: str = ""
        self._current_base_types: list[str] = []
        self._node_id: int = 1
        self._var_types: dict[str, str] = {}

        # Depth of enclosing function-like scopes
        self._function_scope_depth: int = 0
        self._current_function_id: int = 0

        # Track exports for module-level analysis
        self._exported_names: set[str] = set()

    @property
    def exported_names(self) -> set[str]:
        """Names exported by this module (from export statements)."""
        return self._exported_names

    def _current_qname(self) -> str:
        return ".".join(self._context) if self._context else ""

    def _push_scope(self, name: str) -> None:
        self._context.append(name)

    def _pop_scope(self) -> None:
        if self._context:
            self._context.pop()

    def _add_node(self, info: NodeInfo) -> int:
        info.id = self._node_id
        self._node_id += 1
        self.nodes.append(info)
        return info.id

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def visit(self, tree: Any) -> None:
        root = tree.root_node if hasattr(tree, "root_node") else tree
        try:
            self._walk(root)
        except Exception as exc:
            self.warnings.append(
                WarningInfo(
                    warn_type="syntax_error",
                    severity="error",
                    message=f"CST visit error in {self.file_path}: {exc}",
                    file_path=self.file_path,
                )
            )

    # ------------------------------------------------------------------
    # Recursive walk
    # ------------------------------------------------------------------

    def _walk(self, node: Any) -> None:
        ntype = node.type if hasattr(node, "type") else ""

        if ntype == "program":
            for child in node.children:
                self._walk(child)

        elif ntype in _CST_TYPE_TO_NODE_TYPE:
            self._visit_type_declaration(node, ntype)

        elif ntype == "function_declaration" or ntype == "generator_function_declaration":
            self._visit_function(node, is_method=False)

        elif ntype == "arrow_function":
            self._visit_arrow_function(node)

        elif ntype in _TYPE_MEMBER_NODE_TYPES:
            self._visit_member(node, ntype)

        elif ntype == "variable_declaration" or ntype == "lexical_declaration":
            self._visit_variable_declaration(node)

        elif ntype == "import_statement":
            self._visit_import(node)

        elif ntype == "export_statement":
            self._visit_export(node)

        elif ntype == "expression_statement":
            # Check for export default <expr> — expression_statement wrapping export
            for child in node.children:
                self._walk(child)

        elif ntype == "call_expression":
            self._visit_call(node)

        elif ntype == "new_expression":
            self._visit_new(node)

        elif ntype == "member_expression":
            self._visit_member_access(node)

        elif ntype == "assignment_expression":
            self._visit_assignment(node)

        elif ntype == "jsx_element" or ntype == "jsx_self_closing_element":
            self._visit_jsx(node)

        elif ntype == "jsx_fragment":
            for child in node.children:
                self._walk(child)

        elif ntype == "namespace_declaration" or ntype == "internal_module":
            self._visit_namespace(node)

        elif ntype == "decorator":
            pass  # Handled by _extract_decorators

        elif ntype == "ambient_declaration":
            for child in node.children:
                self._walk(child)

        elif ntype in ("identifier",):
            self._visit_identifier_read(node)

        else:
            for child in node.children:
                self._walk(child)

    # ------------------------------------------------------------------
    # Type declarations (class, interface, enum, type alias)
    # ------------------------------------------------------------------

    def _visit_type_declaration(self, node: Any, ntype: str) -> None:
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        name = _node_text(name_node)
        if not name:
            return

        qualified = self._current_qname()
        qualified = qualified + ("." + name if qualified else name)
        node_type = _CST_TYPE_TO_NODE_TYPE.get(ntype, "class")

        dec_names = _extract_decorators(node)
        visibility = _extract_visibility(node)
        doc = self._extract_doc_string(node)

        info = NodeInfo(
            file_id=0,
            name=name,
            qualified_name=qualified,
            node_type=node_type,
            line_start=_node_line(node),
            line_end=_node_end_line(node),
            col_offset=_node_col(node),
            parent_node_id=self._current_type_id,
            decorators=dec_names,
            docstring=doc,
            visibility=visibility,
        )
        nid = self._add_node(info)

        # Emit inherit edges for base types
        base_types = _extract_base_types(node)
        for bt in base_types:
            self.references.append(ReferenceInfo(
                source_qname=qualified,
                target_name=bt,
                edge_type="inherit",
                line=_node_line(node),
            ))
            self.name_usages.add(bt.split(".")[-1])

        # Emit decorate edges for decorators
        for dname in dec_names:
            self.references.append(ReferenceInfo(
                source_qname=qualified,
                target_name=dname,
                edge_type="decorate",
                line=_node_line(node),
            ))

        prev_type_id = self._current_type_id
        prev_type_qname = self._current_type_qname
        prev_base_types = self._current_base_types
        self._current_type_id = nid
        self._current_type_qname = qualified
        self._current_base_types = base_types
        self._push_scope(name)

        body = node.child_by_field_name("body")
        if body:
            self._walk(body)
        else:
            for child in node.children:
                if child == name_node:
                    continue
                if child.type in ("extends_clause", "implements_clause",
                                  "type_parameters", "modifier",
                                  "decorator", "type_annotation",
                                  "abstract", "export", "default"):
                    continue
                self._walk(child)

        self._pop_scope()
        self._current_type_id = prev_type_id
        self._current_type_qname = prev_type_qname
        self._current_base_types = prev_base_types

    # ------------------------------------------------------------------
    # Function declarations (top-level or nested)
    # ------------------------------------------------------------------

    def _visit_function(self, node: Any, is_method: bool = False) -> None:
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        name = _node_text(name_node)
        if not name:
            return

        qualified = self._current_qname()
        qualified = qualified + ("." + name if qualified else name)
        node_type = "method" if is_method else "function"

        dec_names = _extract_decorators(node)
        is_async = _has_modifier(node, "async")
        type_ann = _extract_return_type(node)
        doc = self._extract_doc_string(node)

        info = NodeInfo(
            file_id=0,
            name=name,
            qualified_name=qualified,
            node_type=node_type,
            line_start=_node_line(node),
            line_end=_node_end_line(node),
            col_offset=_node_col(node),
            parent_node_id=self._current_type_id,
            is_async=is_async,
            type_annotation=type_ann,
            decorators=dec_names,
            docstring=doc,
        )
        nid = self._add_node(info)

        for dname in dec_names:
            self.references.append(ReferenceInfo(
                source_qname=qualified,
                target_name=dname,
                edge_type="decorate",
                line=_node_line(node),
            ))

        # Parameter types are uses
        self._emit_signature_type_reads(node, qualified, _node_line(node))

        self._push_scope(name)
        self._function_scope_depth += 1
        prev_function_id = self._current_function_id
        self._current_function_id = nid
        try:
            body = node.child_by_field_name("body")
            if body:
                self._walk(body)
            else:
                for child in node.children:
                    if child == name_node:
                        continue
                    if child.type in ("parameter_list", "return_type", "type_parameters",
                                      "modifier", "decorator", "async", "export",
                                      "semicolon", "type_annotation"):
                        continue
                    self._walk(child)
        finally:
            self._current_function_id = prev_function_id
            self._function_scope_depth -= 1
            self._pop_scope()

    def _visit_arrow_function(self, node: Any) -> None:
        """Arrow functions are anonymous, walk their body only."""
        old_depth = self._function_scope_depth
        self._function_scope_depth += 1
        try:
            # Emit parameter type reads
            self._emit_signature_type_reads(node, self._current_qname(), _node_line(node))
            body = node.child_by_field_name("body")
            if body:
                self._walk(body)
            else:
                for child in node.children:
                    if child.type in ("parameter_list", "return_type", "type_parameters",
                                      "async", "=>"):
                        continue
                    self._walk(child)
        finally:
            self._function_scope_depth = old_depth

    # ------------------------------------------------------------------
    # Class members (methods, properties, getters/setters)
    # ------------------------------------------------------------------

    def _visit_member(self, node: Any, ntype: str) -> None:
        sq = self._current_qname()

        if ntype == "method_definition":
            self._visit_function(node, is_method=True)
            return

        if ntype == "public_field_definition":
            name_node = node.child_by_field_name("name")
            if not name_node:
                return
            name = _node_text(name_node)
            if not name:
                return
            qualified = sq + "." + name if sq else name
            type_ann = _extract_property_type(node)
            visibility = _extract_visibility(node)

            info = NodeInfo(
                file_id=0,
                name=name,
                qualified_name=qualified,
                node_type="property",
                line_start=_node_line(node),
                line_end=_node_end_line(node),
                col_offset=_node_col(node),
                parent_node_id=self._current_type_id,
                type_annotation=type_ann,
                visibility=visibility,
            )
            nid = self._add_node(info)
            # Type annotation edges
            if type_ann:
                self._emit_type_read(
                    _find_type_annotation_node(node), qualified, _node_line(node)
                )
            # Walk initializer
            for child in node.children:
                if child == name_node:
                    continue
                if child.type in ("type_annotation", "type", "modifier",
                                  "visibility", "public", "private", "protected",
                                  "readonly", "static", "abstract", "override",
                                  "async", "declare", "readonly", "optional",
                                  "semicolon", "?", "!"):
                    continue
                self._walk(child)
            return

        if ntype == "property_signature":
            # Interface property
            name_node = node.child_by_field_name("name")
            if not name_node:
                return
            name = _node_text(name_node)
            if not name:
                return
            qualified = sq + "." + name if sq else name
            type_ann = _extract_property_type(node)

            info = NodeInfo(
                file_id=0,
                name=name,
                qualified_name=qualified,
                node_type="property",
                line_start=_node_line(node),
                line_end=_node_end_line(node),
                col_offset=_node_col(node),
                parent_node_id=self._current_type_id,
                type_annotation=type_ann,
            )
            self._add_node(info)
            if type_ann:
                self._emit_type_read(
                    _find_type_annotation_node(node), qualified, _node_line(node)
                )
            return

        if ntype in ("get_accessor", "set_accessor"):
            name_node = node.child_by_field_name("name")
            if not name_node:
                return
            name = _node_text(name_node)
            if not name:
                return
            prefix = "get_" if ntype == "get_accessor" else "set_"
            qualified = sq + "." + prefix + name if sq else prefix + name

            info = NodeInfo(
                file_id=0,
                name=prefix + name,
                qualified_name=qualified,
                node_type="property",
                line_start=_node_line(node),
                line_end=_node_end_line(node),
                col_offset=_node_col(node),
                parent_node_id=self._current_type_id,
            )
            nid = self._add_node(info)

            self._push_scope(prefix + name)
            self._function_scope_depth += 1
            prev_function_id = self._current_function_id
            self._current_function_id = nid
            try:
                body = node.child_by_field_name("body")
                if body:
                    self._walk(body)
                else:
                    for child in node.children:
                        if child == name_node:
                            continue
                        if child.type in ("parameter_list", "return_type", "type_annotation",
                                          "modifier", "semicolon", "get", "set", "async", "static"):
                            continue
                        self._walk(child)
            finally:
                self._current_function_id = prev_function_id
                self._function_scope_depth -= 1
                self._pop_scope()
            return

        if ntype in ("call_signature", "construct_signature", "index_signature"):
            for child in node.children:
                self._walk(child)
            return

    # ------------------------------------------------------------------
    # Variable declarations (var, let, const)
    # ------------------------------------------------------------------

    def _visit_variable_declaration(self, node: Any) -> None:
        sq = self._current_qname()

        # Determine if this is a field declaration (inside a class at depth 0)
        is_class_field = self._current_type_id != 0 and self._function_scope_depth == 0
        is_module_level = self._current_type_id == 0 and self._function_scope_depth == 0
        node_type_val = "field" if is_class_field else "variable"
        parent_id = (
            self._current_type_id
            if is_class_field
            else (self._current_function_id or self._current_type_id or 0)
        )

        # Find variable declarators
        declarators = [c for c in node.children if c.type == "variable_declarator"]

        for decl in declarators:
            name_node = decl.child_by_field_name("name")
            if name_node and name_node.type in ("object_pattern", "array_pattern"):
                # Destructuring: ``const { a, b: c } = expr`` / ``const [x] = a``.
                self._visit_destructuring(name_node, sq, node_type_val, parent_id, decl)
                continue
            if not name_node:
                # Object destructuring: const { a, b } = ...
                pattern = decl.child_by_field_name("pattern")
                if pattern is None:
                    for child in decl.children:
                        if child.type == "object_pattern":
                            pattern = child
                            break
                if pattern:
                    self._visit_destructuring(pattern, sq, node_type_val, parent_id, decl)
                continue

            name = _node_text(name_node)
            if not name:
                continue

            # Type annotation lives on the declarator itself (``const u: User``
            # -> variable_declarator field ``type``), not on the declaration.
            type_node = decl.child_by_field_name("type") or decl.child_by_field_name("type_annotation")
            type_ann = _node_text(type_node) if type_node else ""

            qualified = sq + "." + name if sq else name
            info = NodeInfo(
                file_id=0,
                name=name,
                qualified_name=qualified,
                node_type=node_type_val,
                line_start=_node_line(decl),
                line_end=_node_end_line(decl),
                col_offset=_node_col(decl),
                parent_node_id=parent_id,
                type_annotation=type_ann,
            )
            self._add_node(info)

            # Write edge
            self.references.append(ReferenceInfo(
                source_qname=sq,
                target_name=name,
                edge_type="write",
                line=_node_line(decl),
            ))

            if type_node:
                self._emit_type_read(type_node, qualified, _node_line(decl))

            # Visit initializer
            init = decl.child_by_field_name("value") or decl.child_by_field_name("initializer")
            if init:
                self._walk(init)
            else:
                for child in decl.children:
                    if child == name_node or child.type == "=" or child.type == "array_type" or child.type == "generic_type":
                        continue
                    if child.type == "type_annotation":
                        continue
                    self._walk(child)

    def _visit_destructuring(
        self,
        pattern: Any,
        sq: str,
        node_type_val: str,
        parent_id: int,
        decl: Any,
    ) -> None:
        """Handle destructuring: ``const { a, b: c } = expr``.
        """
        self._declare_pattern(pattern, sq, node_type_val, parent_id)

        # Walk initializer
        init = decl.child_by_field_name("value") or decl.child_by_field_name("initializer")
        if init:
            self._walk(init)

    def _declare_pattern(
        self,
        pattern: Any,
        sq: str,
        node_type_val: str,
        parent_id: int,
    ) -> None:
        """Declare every local binding inside a destructuring pattern."""
        for child in pattern.children:
            t = child.type
            if t in (
                "identifier",
                "shorthand_property_identifier",
                "shorthand_property_identifier_pattern",
            ):
                self._declare_binding(child, sq, node_type_val, parent_id)
            elif t == "pair_pattern":
                value = child.child_by_field_name("value")
                if value is None:
                    for c in child.children:
                        if c.type in (
                            "identifier",
                            "shorthand_property_identifier",
                            "shorthand_property_identifier_pattern",
                        ):
                            self._declare_binding(c, sq, node_type_val, parent_id)
                    continue
                self._declare_pattern_value(value, sq, node_type_val, parent_id)
            elif t in ("assignment_pattern", "object_assignment_pattern"):
                left = child.child_by_field_name("left")
                right = child.child_by_field_name("right")
                if left is not None:
                    self._declare_pattern_value(left, sq, node_type_val, parent_id)
                if right is not None:
                    # Default-value expression
                    self._walk(right)
            elif t == "rest_pattern":
                value = child.child_by_field_name("value")
                if value is not None:
                    self._declare_pattern_value(value, sq, node_type_val, parent_id)

    def _declare_pattern_value(
        self,
        value: Any,
        sq: str,
        node_type_val: str,
        parent_id: int,
    ) -> None:
        """Declare the binding produced by a pattern value (possibly nested)."""
        if value.type in ("object_pattern", "array_pattern"):
            self._declare_pattern(value, sq, node_type_val, parent_id)
        elif value.type in (
            "identifier",
            "shorthand_property_identifier",
            "shorthand_property_identifier_pattern",
        ):
            self._declare_binding(value, sq, node_type_val, parent_id)
        elif value.type in ("assignment_pattern", "object_assignment_pattern"):
            left = value.child_by_field_name("left")
            right = value.child_by_field_name("right")
            if left is not None:
                self._declare_pattern_value(left, sq, node_type_val, parent_id)
            if right is not None:
                self._walk(right)
        else:
            # Unknown nested value
            self._walk(value)

    def _declare_binding(
        self,
        node: Any,
        sq: str,
        node_type_val: str,
        parent_id: int,
    ) -> None:
        """Declare a single destructured binding as a node + write edge."""
        name = _node_text(node)
        if not name:
            return
        qualified = sq + "." + name if sq else name
        info = NodeInfo(
            file_id=0,
            name=name,
            qualified_name=qualified,
            node_type=node_type_val,
            line_start=_node_line(node),
            line_end=_node_end_line(node),
            col_offset=_node_col(node),
            parent_node_id=parent_id,
        )
        self._add_node(info)
        self.references.append(ReferenceInfo(
            source_qname=sq,
            target_name=name,
            edge_type="write",
            line=_node_line(node),
        ))

    # ------------------------------------------------------------------
    # Import statements
    # ------------------------------------------------------------------

    def _visit_import(self, node: Any) -> None:
        info = self.import_analyzer.analyze_import(node)
        if info:
            self.imports.append(info)
        for child in node.children:
            self._walk(child)

    # ------------------------------------------------------------------
    # Export statements
    # ------------------------------------------------------------------

    def _visit_export(self, node: Any) -> None:
        info = self.import_analyzer.analyze_export(node)
        if info:
            self.exports.append(info)
            for name in info.exported_names:
                self._exported_names.add(name)

        # Walk children to capture exported declarations.
        # The ``default`` branch walks the exported declaration itself,
        # so guard the outer loop against walking the same child twice
        walked: set[int] = set()
        for child in node.children:
            if child.type == "default":
                for c in node.children:
                    if c.type in ("function_declaration", "class_declaration",
                                  "arrow_function", "identifier", "call_expression"):
                        self._walk(c)
                        walked.add(id(c))
            elif id(child) in walked or child.type in (
                "source", "string", "semicolon", "type", ";", "import_statement"
            ):
                continue
            else:
                self._walk(child)

    # ------------------------------------------------------------------
    # Call expressions
    # ------------------------------------------------------------------

    def _visit_call(self, node: Any) -> None:
        func = node.child_by_field_name("function")
        if func:
            cname = _call_name_from_expr(func)
            if cname:
                sq = self._current_qname()
                self.references.append(ReferenceInfo(
                    source_qname=sq,
                    target_name=cname,
                    edge_type="call",
                    line=_node_line(node),
                ))
                self.name_usages.add(cname.split(".")[-1])
                # Also emit the full dotted name for entry rules
                dotted = _dotted_call_name(func)
                if dotted and dotted != cname:
                    self.references.append(ReferenceInfo(
                        source_qname=sq,
                        target_name=dotted,
                        edge_type="call",
                        line=_node_line(node),
                    ))

        # Check for require() calls (CommonJS)
        if func and func.type == "identifier" and _node_text(func) == "require":
            req_info = self.import_analyzer.analyze_require(node)
            if req_info:
                self.imports.append(req_info)

        for child in node.children:
            self._walk(child)

    # ------------------------------------------------------------------
    # New expressions
    # ------------------------------------------------------------------

    def _visit_new(self, node: Any) -> None:
        constr = node.child_by_field_name("constructor")
        if constr:
            cname = _scoped_name(constr) if constr.type in ("identifier",) else _call_name_from_expr(constr)
            if cname:
                sq = self._current_qname()
                self.references.append(ReferenceInfo(
                    source_qname=sq,
                    target_name=cname + ".constructor",
                    edge_type="call",
                    line=_node_line(node),
                ))
                self.name_usages.add(cname.split(".")[-1])

        for child in node.children:
            self._walk(child)

    # ------------------------------------------------------------------
    # Member access
    # ------------------------------------------------------------------

    def _visit_member_access(self, node: Any) -> None:
        prop = node.child_by_field_name("property")
        obj = node.child_by_field_name("object")
        parent = node.parent

        # Only emit read references for member access that is NOT part of a
        # call (call already emits a separate call reference).
        if parent and parent.type != "call_expression":
            if obj and prop:
                obj_name = _scoped_name(obj) if obj.type in ("identifier", "this") else ""
                prop_name = _node_text(prop)
                if prop_name:
                    sq = self._current_qname()
                    self.references.append(ReferenceInfo(
                        source_qname=sq,
                        target_name=prop_name,
                        edge_type="read",
                        line=_node_line(node),
                    ))
                    self.name_usages.add(prop_name)

        for child in node.children:
            self._walk(child)

    # ------------------------------------------------------------------
    # Assignment expression
    # ------------------------------------------------------------------

    def _visit_assignment(self, node: Any) -> None:
        left = node.child_by_field_name("left")
        if left:
            target_name = _scoped_name(left) if left.type in ("identifier", "member_expression") else ""
            if target_name:
                sq = self._current_qname()
                self.references.append(ReferenceInfo(
                    source_qname=sq,
                    target_name=target_name,
                    edge_type="write",
                    line=_node_line(node),
                ))

        for child in node.children:
            if child == left:
                continue
            self._walk(child)

    # ------------------------------------------------------------------
    # JSX elements (React components)
    # ------------------------------------------------------------------

    def _visit_jsx(self, node: Any) -> None:
        ntype = node.type
        name_node = None

        if ntype == "jsx_element":
            open_tag = node.child_by_field_name("open_tag")
            if open_tag:
                name_node = open_tag.child_by_field_name("name")
        elif ntype == "jsx_self_closing_element":
            name_node = node.child_by_field_name("name")

        if name_node:
            component_name = _scoped_name(name_node) if name_node.type == "identifier" else _node_text(name_node)
            if component_name:
                sq = self._current_qname()
                self.references.append(ReferenceInfo(
                    source_qname=sq,
                    target_name=component_name,
                    edge_type="call",
                    line=_node_line(node),
                ))
                self.name_usages.add(component_name.split(".")[-1])
                self.references.append(ReferenceInfo(
                    source_qname=sq,
                    target_name=component_name,
                    edge_type="jsx_element",
                    line=_node_line(node),
                ))

        for child in node.children:
            self._walk(child)

    # ------------------------------------------------------------------
    # Namespace / internal module
    # ------------------------------------------------------------------

    def _visit_namespace(self, node: Any) -> None:
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        name = _scoped_name(name_node) if name_node.type != "identifier" else _node_text(name_node)
        if not name:
            return

        qualified = self._current_qname()
        qualified = qualified + ("." + name if qualified else name)

        info = NodeInfo(
            file_id=0,
            name=name,
            qualified_name=qualified,
            node_type="namespace",
            line_start=_node_line(node),
            line_end=_node_end_line(node),
            col_offset=_node_col(node),
            parent_node_id=self._current_type_id,
        )
        nid = self._add_node(info)

        prev_type_id = self._current_type_id
        self._current_type_id = nid
        self._push_scope(name)

        body = node.child_by_field_name("body")
        if body:
            self._walk(body)
        else:
            for child in node.children:
                if child == name_node:
                    continue
                if child.type in ("modifier", "export", "declare", "semicolon"):
                    continue
                self._walk(child)

        self._pop_scope()
        self._current_type_id = prev_type_id

    # ------------------------------------------------------------------
    # Identifier reads
    # ------------------------------------------------------------------

    def _visit_identifier_read(self, node: Any) -> None:
        parent = node.parent
        if not parent:
            return

        ptype = parent.type

        # Export specifiers are declarations
        if ptype == "export_specifier":
            if node == parent.child_by_field_name("alias"):
                return
        elif ptype in ("namespace_export", "export_clause", "named_exports"):
            return

        # Skip: this is a declaration or import, not a reference
        if ptype in (
            "function_declaration", "generator_function_declaration",
            "class_declaration", "abstract_class_declaration",
            "interface_declaration", "enum_declaration",
            "type_alias_declaration", "method_definition",
            "variable_declarator", "import_specifier",
            "named_imports", "import_clause", "import_statement",
            "namespace_import",
            "namespace_declaration", "internal_module",
            "public_field_definition", "property_signature",
            "shorthand_property_identifier",
            "pair_pattern", "object_pattern",
        ):
            # Import bindings are definitions, not references
            if ptype in ("import_specifier", "named_imports", "import_clause",
                         "import_statement", "namespace_import"):
                return
            # Check if this is the name field of the parent, not a reference
            if node == parent.child_by_field_name("name"):
                return
            # For variable_declarator, the name is the definition
            if ptype == "variable_declarator" and node == parent.child_by_field_name("name"):
                return
            # For function_declaration, the name is the definition
            if ptype in ("function_declaration", "generator_function_declaration") and node == parent.child_by_field_name("name"):
                return
            # For class/interface declarations
            if ptype in (
                "class_declaration", "abstract_class_declaration",
                "interface_declaration", "enum_declaration",
                "type_alias_declaration",
            ) and node == parent.child_by_field_name("name"):
                return
            # For method_definition
            if ptype == "method_definition" and node == parent.child_by_field_name("name"):
                return
            # For namespace
            if ptype in ("namespace_declaration", "internal_module") and node == parent.child_by_field_name("name"):
                return

        name = _node_text(node)
        if not name or name in ("import", "export", "default", "from", "as", "type", "typeof", "const", "let", "var", "function", "class", "interface", "enum", "namespace", "abstract", "async", "await", "new", "this", "super", "return", "if", "else", "for", "while", "do", "switch", "case", "break", "continue", "try", "catch", "finally", "throw", "debugger", "with", "yield", "extends", "implements", "static", "public", "private", "protected", "readonly", "declare", "module", "require"):
            return

        sq = self._current_qname()
        self.references.append(ReferenceInfo(
            source_qname=sq,
            target_name=name,
            edge_type="read",
            line=_node_line(node),
        ))
        self.name_usages.add(name)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _emit_signature_type_reads(
        self, node: Any, qualified: str, line: int
    ) -> None:
        """Emit read edges for types referenced in parameters and return."""
        for child in node.children:
            if child.type == "parameter_list" or child.type == "formal_parameters":
                for param in child.children:
                    if param.type == "required_parameter" or param.type == "optional_parameter":
                        ptype = param.child_by_field_name("type_annotation") or param.child_by_field_name("type")
                        if ptype:
                            type_name = _resolve_type_node(ptype)
                            if type_name:
                                self.references.append(ReferenceInfo(
                                    source_qname=qualified,
                                    target_name=type_name,
                                    edge_type="read",
                                    line=line,
                                ))
                                self.name_usages.add(type_name.split(".")[-1])
        # Return type
        rt = node.child_by_field_name("return_type") or node.child_by_field_name("type_annotation")
        if rt:
            type_name = _resolve_type_node(rt)
            if type_name:
                self.references.append(ReferenceInfo(
                    source_qname=qualified,
                    target_name=type_name,
                    edge_type="read",
                    line=line,
                ))
                self.name_usages.add(type_name.split(".")[-1])

    def _emit_type_read(self, type_node: Any, qualified: str, line: int) -> None:
        """Emit a read edge for a type annotation."""
        if type_node is None:
            return
        type_name = _resolve_type_node(type_node)
        if type_name:
            self.references.append(ReferenceInfo(
                source_qname=qualified,
                target_name=type_name,
                edge_type="read",
                line=line,
            ))
            self.name_usages.add(type_name.split(".")[-1])

    def _extract_doc_string(self, node: Any) -> str:
        """Extract JSDoc comment from preceding nodes."""
        lines: list[str] = []
        parent = node.parent
        if parent:
            children = list(parent.children)
            node_idx = None
            for i, child in enumerate(children):
                if child == node:
                    node_idx = i
                    break
            if node_idx is not None:
                for i in range(node_idx - 1, -1, -1):
                    child = children[i]
                    if child.type == "comment":
                        txt = _node_text(child).strip()
                        if txt.startswith("/**") or txt.startswith("*"):
                            lines.insert(0, txt)
                    elif child.type == "decorator":
                        continue
                    else:
                        break
        return "\n".join(lines)


def _resolve_type_node(type_node: Any) -> str:
    """Resolve a type node to its name string."""
    if type_node is None:
        return ""
    if type_node.type == "type_annotation":
        for child in type_node.children:
            if child.type == ":":
                continue
            return _resolve_type_node(child)
    if type_node.type == "generic_type":
        name_node = type_node.child_by_field_name("name")
        if name_node:
            return _node_text(name_node)
    if type_node.type in ("identifier", "type_identifier", "predefined_type"):
        return _node_text(type_node)
    if type_node.type == "member_expression":
        return _scoped_name(type_node)
    if type_node.type == "array_type":
        elem = type_node.child_by_field_name("element")
        if elem:
            return _resolve_type_node(elem)
    if type_node.type == "union_type":
        return ""
    if type_node.type in ("number_type", "string_type", "boolean_type",
                          "void_type", "any_type", "null_type", "undefined_type",
                          "never_type", "object_type", "unknown_type"):
        return ""
    return _node_text(type_node)


def _find_type_annotation_node(node: Any) -> Any | None:
    """Find the type annotation node for a declaration."""
    ta = node.child_by_field_name("type_annotation") or node.child_by_field_name("type")
    if ta:
        return ta
    for child in node.children:
        if child.type == "type_annotation":
            return child
    return None
