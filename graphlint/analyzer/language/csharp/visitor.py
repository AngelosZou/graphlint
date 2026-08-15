# -*- coding: utf-8 -*-
"""Tree-sitter CST visitor — traverses the C# concrete syntax tree to extract
nodes (symbol definitions), structured references (edges), and imports."""

from __future__ import annotations

from typing import Any

from graphlint.analyzer._types import NodeInfo, ReferenceInfo
from graphlint.analyzer.language.csharp.constants import (
    _CST_TYPE_TO_NODE_TYPE,
    _TYPE_MEMBER_NODE_TYPES,
)
from graphlint.analyzer.language.csharp.imports import (
    CSharpImportAnalyzer,
    UseInfo,
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


def _generic_base_name(node: Any) -> str:
    """Base name of a generic type/method reference without type arguments.

    ``List<int>`` → ``"List"``; ``Dictionary<string, T>`` → ``"Dictionary"``.
    Falls back to the node text when the name field is unavailable.
    """
    if node.type == "generic_name":
        name_node = node.child_by_field_name("name")
        if name_node:
            return _node_text(name_node)
        for child in node.children:
            if child.type == "identifier":
                return _node_text(child)
        return _node_text(node)
    return _node_text(node)


def _scoped_name(node: Any) -> str:
    """Extract dotted name from a qualified_name or identifier node.

    Generic segments contribute only their base name so that ``List<int>``
    resolves to ``List`` — the type-argument list is not part of the symbol
    name and would otherwise produce unresolvable garbage targets.
    """
    if node.type == "qualified_name":
        parts = []
        for child in node.children:
            if child.type == "identifier":
                parts.append(_node_text(child))
            elif child.type == "generic_name":
                parts.append(_generic_base_name(child))
            elif child.type == "qualified_name":
                inner = _scoped_name(child)
                if inner:
                    parts.append(inner)
        return ".".join(parts)
    if node.type == "identifier":
        return _node_text(node)
    if node.type == "generic_name":
        return _generic_base_name(node)
    return ""


def _call_name_from_expr(expr_node: Any) -> str:
    """Extract the callable name from an expression node."""
    if expr_node.type == "identifier":
        return _node_text(expr_node)
    if expr_node.type in ("qualified_name",):
        return _scoped_name(expr_node)
    if expr_node.type == "member_access_expression":
        name_node = expr_node.child_by_field_name("name")
        if name_node:
            return _node_text(name_node)
        expr = expr_node.child_by_field_name("expression")
        if expr:
            return _call_name_from_expr(expr)
    if expr_node.type == "generic_name":
        return _generic_base_name(expr_node)
    if expr_node.type == "conditional_access_expression":
        # x?.Method / x?.Prop — the callable name lives in the
        # member_binding_expression (.Method / .Prop).
        for child in expr_node.children:
            if child.type == "member_binding_expression":
                name_node = child.child_by_field_name("name")
                if name_node:
                    return _node_text(name_node)
        return ""
    return ""


def _extract_visibility(node: Any) -> str:
    """Extract access modifier from a definition node's modifier children."""
    for child in node.children:
        if child.type == "modifier":
            txt = _node_text(child)
            if txt in ("public", "private", "protected", "internal"):
                return txt
    return ""


def _has_modifier(node: Any, modifier: str) -> bool:
    """Check if node has a specific modifier keyword."""
    for child in node.children:
        if child.type == "modifier" and _node_text(child) == modifier:
            return True
    return False


def _extract_attributes(node: Any) -> list[str]:
    """Extract ``[Attribute]`` names attached to *node*.

    Newer tree-sitter-c-sharp grammars attach ``attribute_list`` nodes as
    direct children of the declaration; older grammars place them as
    siblings immediately preceding the declaration.  Both layouts are
    handled here.
    """
    names: list[str] = []
    for child in node.children:
        if child.type == "attribute_list":
            for attr_child in child.children:
                if attr_child.type == "attribute":
                    name_node = attr_child.child_by_field_name("name")
                    if name_node:
                        attr_name = _scoped_name(name_node)
                        if attr_name:
                            names.append(attr_name)
    if names:
        return names

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
                if child.type == "attribute_list":
                    for attr_child in child.children:
                        if attr_child.type == "attribute":
                            name_node = attr_child.child_by_field_name("name")
                            if name_node:
                                attr_name = _scoped_name(name_node)
                                if attr_name:
                                    names.insert(0, attr_name)
                elif child.type in ("modifier", "comment", "preprocessor_call"):
                    continue
                else:
                    break
    return names


def _extract_base_types(node: Any) -> list[str]:
    """Extract base class and interface names from a type declaration."""
    bases: list[str] = []
    base_list = node.child_by_field_name("base_list")
    if base_list is None:
        # Newer grammars expose the base list as an anonymous child node
        for child in node.children:
            if child.type == "base_list":
                base_list = child
                break
    if base_list:
        for child in base_list.children:
            if child.type in ("identifier", "qualified_name", "generic_name"):
                bases.append(_scoped_name(child))
    return bases


def _explicit_interface_name(specifier: Any) -> str:
    """Extract the interface name from an ``explicit_interface_specifier``.

    The node text ends with a dot (e.g. ``IFoo.``), so fall back to the first
    identifier/qualified-name child.
    """
    for child in specifier.children:
        if child.type in ("identifier", "qualified_name", "generic_name"):
            return _scoped_name(child) or _node_text(child)
    return _node_text(specifier).rstrip(".").strip()


def _dotted_call_name(expr_node: Any) -> str:
    """Full dotted name of a callable expression (e.g. ``Application.Run``).

    Unlike :func:`_call_name_from_expr` (which returns the leaf name for
    member access so instance calls resolve to local methods), this keeps
    the whole chain: ``Application.Run`` stays ``Application.Run``.  Used
    for ``function_call:`` entry-rule matching and static-class calls.
    """
    if expr_node.type == "member_access_expression":
        name_node = expr_node.child_by_field_name("name")
        expr = expr_node.child_by_field_name("expression")
        base = _dotted_call_name(expr) if expr is not None else ""
        nm = _node_text(name_node) if name_node else ""
        if base and nm:
            return base + "." + nm
        return nm
    return _call_name_from_expr(expr_node)


def _infer_var_type(decl: Any) -> str:
    """Infer a ``var`` local's type from its initializer expression.

    ``var u = new User(...)`` → ``"User"``.  Returns ``""`` when the
    initializer does not carry a usable type (e.g. ``new()`` target-typed
    creation, method calls, literals).
    """
    init = CSharpVisitor._find_declarator_initializer(decl)
    if init is None:
        return ""
    if init.type == "object_creation_expression":
        type_node = init.child_by_field_name("type")
        if type_node:
            return _scoped_name(type_node) or _node_text(type_node)
    return ""


class CSharpVisitor:
    """Walks a tree-sitter CST of C# and extracts nodes, references,
    and imports."""

    def __init__(
        self,
        namespace_qname: str,
        file_path: str,
        import_analyzer: CSharpImportAnalyzer,
    ) -> None:
        self.namespace_qname = namespace_qname
        self.file_path = file_path
        self.import_analyzer = import_analyzer

        self.nodes: list[NodeInfo] = []
        self.references: list[ReferenceInfo] = []
        self.name_usages: set[str] = set()
        self.uses: list[UseInfo] = []
        self.warnings: list[Any] = []

        self._context: list[str] = []
        self._current_type_id: int = 0
        self._current_type_qname: str = ""
        self._current_base_types: list[str] = []
        self._node_id: int = 1
        self._field_qnames: set[str] = set()

        # Properties per type (qualified_type_name -> set of names),
        # for accessor-call resolution.
        self._type_properties: dict[str, set[str]] = {}
        # All property names, flat (fast negative check).
        self._all_property_names: set[str] = set()

        # Types declaring an indexer (``this[]``), for ``obj[i]`` resolution.
        self._type_indexers: set[str] = set()

        # Local variable types (variable_name -> type_name).
        self._var_types: dict[str, str] = {}

        # Depth of enclosing method-like scopes (method/accessor/lambda
        # bodies), distinguishing fields from locals.
        self._method_scope_depth: int = 0

        # Node id of the innermost enclosing method-like declaration;
        # local variables are parented to it.
        self._current_method_id: int = 0

        # Deduplicate inherit edges for explicit interface members.
        self._explicit_inherits: set[tuple[str, str]] = set()

    def _current_qname(self) -> str:
        return ".".join(self._context) if self._context else ""

    def _push_scope(self, name: str) -> None:
        self._context.append(name)

    def _pop_scope(self) -> None:
        if self._context:
            self._context.pop()

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def visit(self, tree: Any) -> None:
        root = tree.root_node if hasattr(tree, "root_node") else tree
        try:
            self._walk(root)
        except Exception as exc:
            # Keep the partial graph; surface the error to the parser.
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

        if ntype == "compilation_unit":
            # A file-scoped namespace (``namespace MyApp;``) is a sibling
            # of the top-level members; apply it as a scope around them.
            children = list(node.children)
            ns_idx = -1
            ns_name = ""
            for i, child in enumerate(children):
                if child.type == "file_scoped_namespace_declaration":
                    name_node = child.child_by_field_name("name")
                    ns_name = _scoped_name(name_node) if name_node else ""
                    ns_idx = i
                    break
            if ns_idx >= 0 and ns_name:
                self._push_scope(ns_name)
                for i, child in enumerate(children):
                    if i != ns_idx:
                        self._walk(child)
                self._pop_scope()
            elif ns_idx >= 0:
                for i, child in enumerate(children):
                    if i != ns_idx:
                        self._walk(child)
            else:
                for child in children:
                    self._walk(child)

        elif ntype == "namespace_declaration":
            self._visit_namespace(node)

        elif ntype == "file_scoped_namespace_declaration":
            self._visit_file_scoped_namespace(node)

        elif ntype in _CST_TYPE_TO_NODE_TYPE:
            self._visit_type_declaration(node, ntype)

        elif ntype in _TYPE_MEMBER_NODE_TYPES:
            self._visit_member(node, ntype)

        elif ntype == "using_directive":
            self._visit_using(node)

        elif ntype == "variable_declaration":
            self._visit_variable_declaration(node)

        elif ntype == "invocation_expression":
            self._visit_call(node)

        elif ntype == "object_creation_expression":
            self._visit_object_creation(node)

        elif ntype == "member_access_expression":
            self._visit_member_access(node)

        elif ntype == "assignment_expression":
            self._visit_assignment(node)

        elif ntype == "lambda_expression":
            self._visit_lambda(node)

        elif ntype == "enum_member_declaration":
            self._visit_enum_member(node)

        elif ntype in ("declaration_pattern", "var_pattern"):
            self._visit_pattern_variable(node)

        elif ntype in ("is_pattern_expression", "is_expression"):
            self._visit_is_expression(node)

        elif ntype == "as_expression":
            self._visit_type_check_expression(node)

        elif ntype == "cast_expression":
            self._visit_type_check_expression(node)

        elif ntype == "catch_clause":
            self._visit_catch(node)

        elif ntype == "foreach_statement":
            self._visit_foreach(node)

        elif ntype == "local_function_statement":
            self._visit_local_function(node)

        elif ntype == "accessor_declaration":
            # get/set/init accessor bodies are method-like scopes
            self._method_scope_depth += 1
            try:
                for child in node.children:
                    self._walk(child)
            finally:
                self._method_scope_depth -= 1

        elif ntype == "element_access_expression":
            self._visit_element_access(node)

        elif ntype in ("typeof_expression", "sizeof_expression", "default_expression"):
            self._visit_typeof_expression(node)

        elif ntype in ("attribute_list", "attribute"):
            pass

        elif ntype in ("identifier", "qualified_name", "generic_name"):
            self._visit_identifier_read(node)

        else:
            for child in node.children:
                self._walk(child)

    # ------------------------------------------------------------------
    # Namespace
    # ------------------------------------------------------------------

    def _visit_namespace(self, node: Any) -> None:
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        name = _scoped_name(name_node)
        if not name:
            return
        self._push_scope(name)
        body = node.child_by_field_name("body")
        if body:
            self._walk(body)
        else:
            for child in node.children:
                self._walk(child)
        self._pop_scope()

    def _visit_file_scoped_namespace(self, node: Any) -> None:
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        name = _scoped_name(name_node)
        if not name:
            return
        self._push_scope(name)
        for child in node.children:
            if child.type not in ("semicolon",):
                self._walk(child)
        self._pop_scope()

    # ------------------------------------------------------------------
    # Type declarations
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

        is_partial = _has_modifier(node, "partial")
        if is_partial:
            can_name = qualified
            qualified = qualified + "#partial:" + self.file_path

        dec_names = _extract_attributes(node)
        visibility = _extract_visibility(node)
        doc = self._extract_doc(node)

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
            is_partial=is_partial,
            canonical_name=can_name if is_partial else "",
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

        # Emit decorate edges for attributes
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
        self._current_type_qname = can_name if is_partial else qualified
        self._current_base_types = base_types
        self._push_scope(name)

        body = node.child_by_field_name("body")
        if body:
            self._walk(body)
        else:
            for child in node.children:
                if child == name_node:
                    continue  # declaring the name is not a use (no self-read)
                if child.type in ("base_list", "type_parameter_list",
                                  "type_parameter_constraints_clause",
                                  "modifier", "attribute_list", "keyword",
                                  "equals_value_clause", "arrow_expression_clause",
                                  "parameter_list"):
                    continue
                self._walk(child)

        self._pop_scope()
        self._current_type_id = prev_type_id
        self._current_type_qname = prev_type_qname
        self._current_base_types = prev_base_types

    # ------------------------------------------------------------------
    # Member declarations (methods, properties, constructors, etc.)
    # ------------------------------------------------------------------

    def _visit_member(self, node: Any, ntype: str) -> None:
        self._check_explicit_interface(node)
        if ntype == "field_declaration":
            # Delegate to children (variable_declaration) without
            # re-dispatching this same node (that would recurse forever).
            for child in node.children:
                self._walk(child)
            return
        if ntype == "event_declaration":
            self._visit_event(node)
            return
        if ntype == "event_field_declaration":
            self._visit_event(node)
            return
        if ntype == "constructor_declaration":
            self._visit_constructor(node)
            return
        if ntype == "destructor_declaration":
            self._visit_destructor(node)
            return
        if ntype == "property_declaration":
            self._visit_property(node)
            return
        if ntype == "indexer_declaration":
            self._visit_indexer(node)
            return
        if ntype == "operator_declaration" or ntype == "conversion_operator_declaration":
            self._visit_operator(node)
            return
        if ntype == "method_declaration":
            self._visit_method(node)
            return

    def _visit_method(self, node: Any) -> None:
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        name = _node_text(name_node)
        if not name:
            return

        qualified = self._current_qname() + "." + name
        dec_names = _extract_attributes(node)
        visibility = _extract_visibility(node)
        doc = self._extract_doc(node)
        is_async = _has_modifier(node, "async")
        is_deprecated = self._check_deprecated(node, doc)
        type_ann = self._extract_return_type(node)

        info = NodeInfo(
            file_id=0,
            name=name,
            qualified_name=qualified,
            node_type="method",
            line_start=_node_line(node),
            line_end=_node_end_line(node),
            col_offset=_node_col(node),
            parent_node_id=self._current_type_id,
            is_deprecated=is_deprecated,
            type_annotation=type_ann,
            is_async=is_async,
            decorators=dec_names,
            docstring=doc,
            visibility=visibility,
        )
        nid = self._add_node(info)

        # Explicit interface implementations inherit from their interface.
        for child in node.children:
            if child.type == "explicit_interface_specifier":
                iface_name = _explicit_interface_name(child)
                if iface_name:
                    key = (qualified, iface_name)
                    if key not in self._explicit_inherits:
                        self._explicit_inherits.add(key)
                        self.references.append(ReferenceInfo(
                            source_qname=qualified,
                            target_name=iface_name,
                            edge_type="inherit",
                            line=_node_line(child),
                        ))
                break

        for dname in dec_names:
            self.references.append(ReferenceInfo(
                source_qname=qualified,
                target_name=dname,
                edge_type="decorate",
                line=_node_line(node),
            ))

        self._push_scope(name)
        self._method_scope_depth += 1
        prev_method_id = self._current_method_id
        self._current_method_id = nid
        # Signature types are uses: a type referenced only in the
        # return/parameter list must still produce a read edge.
        self._emit_signature_type_reads(node, qualified, _node_line(node))
        try:
            body = node.child_by_field_name("body")
            if body:
                self._walk(body)
            else:
                for child in node.children:
                    if child == name_node:
                        continue  # declaring the name is not a use (no self-read)
                    if child.type in ("modifier", "attribute_list", "type",
                                      "type_parameter_list",
                                      "type_parameter_constraints_clause",
                                      "parameter_list", "return_type",
                                      "arrow_expression_clause", "semicolon"):
                        continue
                    self._walk(child)
        finally:
            self._current_method_id = prev_method_id
            self._method_scope_depth -= 1
            self._pop_scope()

    def _visit_constructor(self, node: Any) -> None:
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        name = _node_text(name_node)
        if not name:
            return
        qualified = self._current_qname() + "." + ".ctor"
        dec_names = _extract_attributes(node)
        doc = self._extract_doc(node)
        visibility = _extract_visibility(node)

        info = NodeInfo(
            file_id=0,
            name=".ctor",
            qualified_name=qualified,
            node_type="constructor",
            line_start=_node_line(node),
            line_end=_node_end_line(node),
            col_offset=_node_col(node),
            parent_node_id=self._current_type_id,
            decorators=dec_names,
            docstring=doc,
            visibility=visibility,
        )
        nid = self._add_node(info)

        for dname in dec_names:
            self.references.append(ReferenceInfo(
                source_qname=qualified,
                target_name=dname,
                edge_type="decorate",
                line=_node_line(node),
            ))

        self._push_scope(".ctor")

        # Parameter types are uses (constructor has no return type).
        self._emit_signature_type_reads(node, qualified, _node_line(node))

        for child in node.children:
            if child.type == "constructor_initializer":
                for c in child.children:
                    txt = _node_text(c)
                    if txt == "this":
                        self.references.append(ReferenceInfo(
                            source_qname=qualified,
                            target_name=qualified,
                            edge_type="call",
                            line=_node_line(child),
                        ))
                        break
                    elif txt == "base" and self._current_base_types:
                        for bt in self._current_base_types:
                            self.references.append(ReferenceInfo(
                                source_qname=qualified,
                                target_name=bt + "..ctor",
                                edge_type="call",
                                line=_node_line(child),
                            ))
                        break
                break

        self._method_scope_depth += 1
        prev_method_id = self._current_method_id
        self._current_method_id = nid
        try:
            body = node.child_by_field_name("body")
            if body:
                self._walk(body)
            else:
                for child in node.children:
                    if child.type in ("modifier", "attribute_list", "parameter_list",
                                      "initializer", "arrow_expression_clause", "semicolon"):
                        continue
                    self._walk(child)
        finally:
            self._current_method_id = prev_method_id
            self._method_scope_depth -= 1
            self._pop_scope()

    def _visit_destructor(self, node: Any) -> None:
        qualified = self._current_qname() + ".Finalize"
        dec_names = _extract_attributes(node)
        doc = self._extract_doc(node)
        visibility = _extract_visibility(node)

        info = NodeInfo(
            file_id=0,
            name="Finalize",
            qualified_name=qualified,
            node_type="destructor",
            line_start=_node_line(node),
            line_end=_node_end_line(node),
            col_offset=_node_col(node),
            parent_node_id=self._current_type_id,
            decorators=dec_names,
            docstring=doc,
            visibility=visibility,
        )
        nid = self._add_node(info)
        self._push_scope("Finalize")
        self._method_scope_depth += 1
        prev_method_id = self._current_method_id
        self._current_method_id = nid
        try:
            body = node.child_by_field_name("body")
            if body:
                self._walk(body)
        finally:
            self._current_method_id = prev_method_id
            self._method_scope_depth -= 1
            self._pop_scope()

    def _visit_property(self, node: Any) -> None:
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        name = _node_text(name_node)
        if not name:
            return

        qualified = self._current_qname() + "." + name
        dec_names = _extract_attributes(node)
        visibility = _extract_visibility(node)
        doc = self._extract_doc(node)
        is_deprecated = self._check_deprecated(node, doc)
        type_ann = self._extract_property_type(node)

        info = NodeInfo(
            file_id=0,
            name=name,
            qualified_name=qualified,
            node_type="property",
            line_start=_node_line(node),
            line_end=_node_end_line(node),
            col_offset=_node_col(node),
            parent_node_id=self._current_type_id,
            is_deprecated=is_deprecated,
            type_annotation=type_ann,
            decorators=dec_names,
            docstring=doc,
            visibility=visibility,
        )
        nid = self._add_node(info)

        for dname in dec_names:
            self.references.append(ReferenceInfo(
                source_qname=qualified,
                target_name=dname,
                edge_type="decorate",
                line=_node_line(node),
            ))

        # Register property for the owning type (member access resolves
        # calls to get_Name / set_Name).
        tq = self._current_type_qname
        if tq:
            if tq not in self._type_properties:
                self._type_properties[tq] = set()
            self._type_properties[tq].add(name)
            self._all_property_names.add(name)

        # A type referenced only by the property declaration is still a use.
        ptype = node.child_by_field_name("type")
        if ptype is not None:
            self._emit_type_read(ptype, qualified, _node_line(node))

        self._push_scope(name)
        # Accessor bodies (get/set/init) are method-like scopes: locals
        # inside them belong to the property, not the enclosing class.
        prev_method_id = self._current_method_id
        self._current_method_id = nid
        try:
            # Field name is ``accessors`` in current tree-sitter-c-sharp
            # grammars (``accessor_list`` in older ones) — check both.
            accessor_list = (
                node.child_by_field_name("accessors")
                or node.child_by_field_name("accessor_list")
            )
            if accessor_list:
                for child in accessor_list.children:
                    self._walk(child)
            else:
                for child in node.children:
                    # Skip the property name and type — declaring them is
                    # not a use; walk the rest (e.g. ``P => _x`` bodies).
                    if child == name_node or child.type == "type":
                        continue
                    if child.type in ("modifier", "attribute_list",
                                      "equals_value_clause", "semicolon",
                                      "keyword"):
                        continue
                    self._walk(child)
        finally:
            self._current_method_id = prev_method_id
            self._pop_scope()

    def _visit_event(self, node: Any) -> None:
        # ``event_declaration`` (with accessors): name is a direct field.
        # ``event_field_declaration`` (``public event A E1, E2;``): the names
        # live in variable_declarator children — one event symbol each.
        name_node = node.child_by_field_name("name")

        if name_node is None:
            for child in node.children:
                if child.type == "variable_declaration":
                    for decl in child.children:
                        if decl.type != "variable_declarator":
                            continue
                        dname_node = decl.child_by_field_name("name")
                        if not dname_node:
                            continue
                        self._emit_event_node(node, _node_text(dname_node), decl)
            return

        name = _node_text(name_node)
        if not name:
            return
        self._emit_event_node(node, name, node)

    def _emit_event_node(self, node: Any, name: str, loc_node: Any) -> None:
        """Create an ``event`` node and walk add/remove accessor bodies."""
        if not name:
            return
        qualified = self._current_qname() + "." + name
        dec_names = _extract_attributes(node)
        doc = self._extract_doc(node)
        visibility = _extract_visibility(node)

        info = NodeInfo(
            file_id=0,
            name=name,
            qualified_name=qualified,
            node_type="event",
            line_start=_node_line(loc_node),
            line_end=_node_end_line(loc_node),
            col_offset=_node_col(loc_node),
            parent_node_id=self._current_type_id,
            decorators=dec_names,
            docstring=doc,
            visibility=visibility,
        )
        nid = self._add_node(info)

        for dname in dec_names:
            self.references.append(ReferenceInfo(
                source_qname=qualified,
                target_name=dname,
                edge_type="decorate",
                line=_node_line(node),
            ))

        # Custom add/remove accessor bodies are method-like scopes.
        self._push_scope(name)
        prev_method_id = self._current_method_id
        self._current_method_id = nid
        try:
            accessor_list = (
                node.child_by_field_name("accessors")
                or node.child_by_field_name("accessor_list")
            )
            if accessor_list:
                for child in accessor_list.children:
                    self._walk(child)
        finally:
            self._current_method_id = prev_method_id
            self._pop_scope()

    def _visit_indexer(self, node: Any) -> None:
        qualified = self._current_qname() + ".this[]"
        dec_names = _extract_attributes(node)
        doc = self._extract_doc(node)
        visibility = _extract_visibility(node)

        info = NodeInfo(
            file_id=0,
            name="this[]",
            qualified_name=qualified,
            node_type="indexer",
            line_start=_node_line(node),
            line_end=_node_end_line(node),
            col_offset=_node_col(node),
            parent_node_id=self._current_type_id,
            decorators=dec_names,
            docstring=doc,
            visibility=visibility,
        )
        nid = self._add_node(info)

        # Register the declaring type for instance indexer access
        # (receiver type -> ``<type>.this[]``).
        tq = self._current_type_qname
        if tq:
            self._type_indexers.add(tq)

        for dname in dec_names:
            self.references.append(ReferenceInfo(
                source_qname=qualified,
                target_name=dname,
                edge_type="decorate",
                line=_node_line(node),
            ))

        # Indexer accessor bodies (get/set) are method-like scopes.
        self._push_scope("this[]")
        prev_method_id = self._current_method_id
        self._current_method_id = nid
        # Indexer type/parameter types are uses (accessor walk skips them).
        self._emit_signature_type_reads(node, qualified, _node_line(node))
        try:
            accessor_list = (
                node.child_by_field_name("accessors")
                or node.child_by_field_name("accessor_list")
            )
            if accessor_list:
                for child in accessor_list.children:
                    self._walk(child)
            else:
                for child in node.children:
                    if child.type in ("modifier", "attribute_list", "type",
                                      "bracketed_parameter_list", "this",
                                      "semicolon", "keyword"):
                        continue
                    self._walk(child)
        finally:
            self._current_method_id = prev_method_id
            self._pop_scope()

    def _visit_operator(self, node: Any) -> None:
        """Handle operator and conversion_operator declarations."""
        op_name = ""
        # Current grammars (0.23.x): ``operator +`` stores the token in the
        # ``operator`` field; conversion operators use ``implicit`` /
        # ``explicit`` keyword children.
        token = node.child_by_field_name("operator")
        if token is not None:
            op_tokens = {
                "+": "op_Addition", "-": "op_Subtraction", "*": "op_Multiply",
                "/": "op_Division", "%": "op_Modulus", "==": "op_Equality",
                "!=": "op_Inequality", "<": "op_LessThan", ">": "op_GreaterThan",
                "<=": "op_LessThanOrEqual", ">=": "op_GreaterThanOrEqual",
                "|": "op_BitwiseOr", "&": "op_BitwiseAnd", "^": "op_ExclusiveOr",
                "<<": "op_LeftShift", ">>": "op_RightShift", "!": "op_LogicalNot",
                "~": "op_OnesComplement", "++": "op_Increment", "--": "op_Decrement",
            }
            op_name = op_tokens.get(_node_text(token), "")
        if not op_name:
            # Older grammar layouts / conversion keywords
            for child in node.children:
                if child.type in ("implicit", "explicit"):
                    op_name = "op_" + child.type.capitalize()
                    break
                if child.type in ("implicit_keyword", "explicit_keyword"):
                    op_name = "op_" + child.type.split("_")[0].capitalize()
                    break
                if child.type in ("plus_token", "minus_token", "asterisk", "slash",
                                  "percent", "equals_equals", "exclamation_equals",
                                  "less_than", "greater_than", "less_than_equals",
                                  "greater_than_equals", "bar", "ampersand",
                                  "caret", "less_less", "greater_greater",
                                  "exclamation", "tilde", "plus_plus", "minus_minus"):
                    op_tokens_old = {
                        "plus_token": "op_Addition", "minus_token": "op_Subtraction",
                        "asterisk": "op_Multiply", "slash": "op_Division",
                        "percent": "op_Modulus", "equals_equals": "op_Equality",
                        "exclamation_equals": "op_Inequality",
                        "less_than": "op_LessThan", "greater_than": "op_GreaterThan",
                        "less_than_equals": "op_LessThanOrEqual",
                        "greater_than_equals": "op_GreaterThanOrEqual",
                        "bar": "op_BitwiseOr", "ampersand": "op_BitwiseAnd",
                        "caret": "op_ExclusiveOr", "less_less": "op_LeftShift",
                        "greater_greater": "op_RightShift",
                        "exclamation": "op_LogicalNot", "tilde": "op_OnesComplement",
                        "plus_plus": "op_Increment", "minus_minus": "op_Decrement",
                    }
                    op_name = op_tokens_old.get(child.type, "")
                    break

        if not op_name:
            op_name = "operator"

        qualified = self._current_qname() + "." + op_name
        dec_names = _extract_attributes(node)
        doc = self._extract_doc(node)
        visibility = _extract_visibility(node)
        if not visibility:
            # C# requires operator overloads to be ``public static``.
            visibility = "public"

        info = NodeInfo(
            file_id=0,
            name=op_name,
            qualified_name=qualified,
            node_type="operator",
            line_start=_node_line(node),
            line_end=_node_end_line(node),
            col_offset=_node_col(node),
            parent_node_id=self._current_type_id,
            decorators=dec_names,
            docstring=doc,
            visibility=visibility,
        )
        nid = self._add_node(info)

        self._push_scope(op_name)
        self._method_scope_depth += 1
        prev_method_id = self._current_method_id
        self._current_method_id = nid
        # Return/parameter types are uses (the body walk below skips them).
        self._emit_signature_type_reads(node, qualified, _node_line(node))
        try:
            body = node.child_by_field_name("body")
            if body:
                self._walk(body)
            else:
                for child in node.children:
                    if child.type in ("modifier", "attribute_list", "parameter_list",
                                      "type", "return_type", "arrow_expression_clause",
                                      "semicolon"):
                        continue
                    self._walk(child)
        finally:
            self._current_method_id = prev_method_id
            self._method_scope_depth -= 1
            self._pop_scope()

    def _visit_variable_declaration(self, node: Any) -> None:
        """Handle variable/field declarations inside methods or types.

        Newer tree-sitter-c-sharp grammars wrap each name and its initializer
        in a ``variable_declarator`` child; older grammars expose the name
        directly on ``variable_declaration``.  Both layouts are supported.
        """
        sq = self._current_qname()
        type_node = node.child_by_field_name("type")
        type_ann = _node_text(type_node) if type_node else ""

        # Field (type level) vs local variable (method scope).
        is_field = self._current_type_id != 0 and self._method_scope_depth == 0
        node_type_val = "field" if is_field else "variable"
        parent_id = (
            self._current_type_id
            if is_field
            else (self._current_method_id or self._current_type_id or 0)
        )

        declarators = [c for c in node.children if c.type == "variable_declarator"]
        targets = declarators if declarators else [node]

        for decl in targets:
            name_node = decl.child_by_field_name("name")
            if not name_node:
                # Tuple deconstruction: ``var (a, b) = GetPair()`` — the
                # tuple_pattern children are the bound variables.
                self._visit_tuple_declarator(decl, sq, type_node, type_ann)
                continue
            name = _node_text(name_node)
            if not name:
                continue

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

            # Write edge: the scope writes to this variable/field
            self.references.append(ReferenceInfo(
                source_qname=sq,
                target_name=name,
                edge_type="write",
                line=_node_line(decl),
            ))

            # Register type for member-access / indexer disambiguation:
            # ``var`` locals infer their type from the initializer;
            # explicitly-typed fields are recorded too.
            if (
                type_ann
                and type_ann != "var"
                and type_node is not None
                and type_node.type != "implicit_type"
            ):
                self._var_types[name] = type_ann
            elif not is_field:
                inferred = _infer_var_type(decl)
                if inferred:
                    self._var_types[name] = inferred

            # Visit initializer
            init = self._find_declarator_initializer(decl)
            if init is not None:
                self._walk(init)
            else:
                for child in decl.children:
                    if child == name_node or child == type_node:
                        continue
                    if child.type in ("=", ";", "semicolon", "var_keyword"):
                        continue
                    self._walk(child)

        # Read edge for the type annotation (once per declaration)
        if type_node and type_ann and type_node.type != "implicit_type":
            self._emit_type_read(type_node, sq, _node_line(node))

    def _visit_tuple_declarator(
        self,
        decl: Any,
        sq: str,
        type_node: Any,
        type_ann: str,
    ) -> None:
        """Handle ``var (a, b) = expr;`` tuple deconstruction.

        Each identifier inside the declarator's ``tuple_pattern`` is a bound
        variable; the initializer expression (typically a call) is walked so
        its references survive.
        """
        pattern = None
        for child in decl.children:
            if child.type == "tuple_pattern":
                pattern = child
                break
        if pattern is None:
            # No tuple pattern — walk children as a fallback so nothing is
            # silently dropped.
            for child in decl.children:
                if child.type == "=":
                    continue
                self._walk(child)
            return

        is_field = self._current_type_id != 0 and self._method_scope_depth == 0
        parent_id = (
            self._current_type_id
            if is_field
            else (self._current_method_id or self._current_type_id or 0)
        )
        for elem in pattern.children:
            if elem.type != "identifier":
                continue
            name = _node_text(elem)
            if not name:
                continue
            qualified = sq + "." + name if sq else name
            info = NodeInfo(
                file_id=0,
                name=name,
                qualified_name=qualified,
                node_type="variable",
                line_start=_node_line(elem),
                line_end=_node_end_line(elem),
                col_offset=_node_col(elem),
                parent_node_id=parent_id,
                type_annotation=type_ann,
            )
            self._add_node(info)
            self.references.append(ReferenceInfo(
                source_qname=sq,
                target_name=name,
                edge_type="write",
                line=_node_line(elem),
            ))
            self.name_usages.add(name)

        # Walk the initializer (GetPair() call etc.), keeping its call edge.
        init = self._find_declarator_initializer(decl)
        if init is not None:
            self._walk(init)

    @staticmethod
    def _find_declarator_initializer(decl: Any) -> Any | None:
        """Locate the initializer expression of a declarator node.

        Older grammars use an ``equals_value_clause`` field; newer grammars
        keep the initializer as an anonymous expression child after ``=``.
        """
        init = (
            decl.child_by_field_name("initializer")
            or decl.child_by_field_name("equals_value_clause")
            or decl.child_by_field_name("value")
        )
        if init is not None:
            return init
        name_node = decl.child_by_field_name("name")
        for child in decl.children:
            if child.type == "=":
                continue
            if child == name_node:
                continue
            if child.type == "tuple_pattern":
                continue
            if child.is_named:
                return child
        return None
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
                # Also emit the full dotted name (Application.Run) for
                # ``function_call:`` entry rules.
                dotted = _dotted_call_name(func)
                if dotted and dotted != cname:
                    self.references.append(ReferenceInfo(
                        source_qname=sq,
                        target_name=dotted,
                        edge_type="call",
                        line=_node_line(node),
                    ))

        for child in node.children:
            self._walk(child)

    def _visit_object_creation(self, node: Any) -> None:
        """Handle ``new Foo(...)`` — call edge to constructor."""
        type_node = node.child_by_field_name("type")
        if type_node:
            cname = (
                _scoped_name(type_node)
                if type_node.type in ("qualified_name", "identifier", "generic_name")
                else _generic_base_name(type_node)
            )
            if cname:
                sq = self._current_qname()
                self.references.append(ReferenceInfo(
                    source_qname=sq,
                    target_name=cname + "..ctor",
                    edge_type="call",
                    line=_node_line(node),
                ))
                self.name_usages.add(cname.split(".")[-1])

        for child in node.children:
            self._walk(child)

    def _match_property_types(self, expr: Any, member_name: str) -> list[str] | None:
        """Resolve which types' property *member_name* an expression reads.

        C# semantics: ``obj.Prop`` is a getter invocation bound at compile
        time to the *declared type* of ``obj``.  We approximate that by:

        - ``this.Prop`` / ``base.Prop`` → the current type;
        - ``varName.Prop`` → the recorded type of ``varName`` (explicit type
          annotation or inferred from ``new`` in the initializer);
        - otherwise (unknown receiver) → all types that declare the property.

        Returns the list of matching type qnames, or ``None`` when the
        expression is not identifiable as a property receiver (callers then
        fall back to a plain read edge).
        """
        if member_name not in self._all_property_names:
            # No declared property anywhere → not a property access
            return None

        candidates: list[str] = []
        if expr is None:
            return None
        if expr.type == "identifier":
            base_type = self._var_types.get(_node_text(expr), "")
            for tq, props in self._type_properties.items():
                if member_name not in props:
                    continue
                if base_type and not (tq.endswith("." + base_type) or tq == base_type):
                    continue
                candidates.append(tq)
            if not base_type:
                return candidates if candidates else None
            return candidates or None
        if expr.type in ("this_expression", "base_expression"):
            tq = self._current_type_qname
            if tq and member_name in self._type_properties.get(tq, set()):
                return [tq]
            return None
        return None

    def _visit_member_access(self, node: Any) -> None:
        """Handle ``obj.member`` — read edge (or call edge for properties)."""
        expr = node.child_by_field_name("expression")
        name_node = node.child_by_field_name("name")

        if not name_node:
            for child in node.children:
                self._walk(child)
            return

        member_name = _node_text(name_node)
        sq = self._current_qname()

        if member_name:
            # Property access (obj.Prop) is a getter invocation in C# —
            # emit a call edge to the property node.
            prop_targets = self._match_property_types(expr, member_name)
            if prop_targets:
                self.references.append(ReferenceInfo(
                    source_qname=sq,
                    target_name=member_name,
                    edge_type="call",
                    line=_node_line(node),
                ))
                self.name_usages.add(member_name)
            else:
                self.references.append(ReferenceInfo(
                    source_qname=sq,
                    target_name=member_name,
                    edge_type="read",
                    line=_node_line(node),
                ))
                self.name_usages.add(member_name)

        for child in node.children:
            self._walk(child)

    # ------------------------------------------------------------------
    # Assignment
    # ------------------------------------------------------------------

    def _visit_assignment(self, node: Any) -> None:
        sq = self._current_qname()
        left = node.child_by_field_name("left")

        if left:
            self._emit_write_ref(left, sq, _node_line(node))

        for child in node.children:
            self._walk(child)

    # ------------------------------------------------------------------
    # Lambda expressions
    # ------------------------------------------------------------------

    def _visit_lambda(self, node: Any) -> None:
        body = node.child_by_field_name("body")
        self._method_scope_depth += 1
        try:
            if body:
                self._walk(body)
            else:
                for child in node.children:
                    if child.type in ("parameter_list", "arrow", "parenthesized_lambda_expression"):
                        continue
                    self._walk(child)
        finally:
            self._method_scope_depth -= 1

    # ------------------------------------------------------------------
    # Enum members
    # ------------------------------------------------------------------

    def _visit_enum_member(self, node: Any) -> None:
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        name = _node_text(name_node)
        if not name:
            return
        qualified = self._current_qname() + "." + name
        info = NodeInfo(
            file_id=0, name=name, qualified_name=qualified,
            node_type="enum_member",
            line_start=_node_line(node), line_end=_node_end_line(node),
            col_offset=_node_col(node),
            parent_node_id=self._current_type_id,
        )
        self._add_node(info)
        # Walk the member's initializer (``Low = 5``) but not the bare name
        # identifier — reading one's own declaration is not a use.
        for child in node.children:
            if child == name_node:
                continue
            self._walk(child)

    # ------------------------------------------------------------------
    # Pattern matching variables  (high priority)
    # ------------------------------------------------------------------

    def _visit_pattern_variable(self, node: Any) -> None:
        """Extract bound variables from ``declaration_pattern`` /
        ``var_pattern``."""
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        name = _node_text(name_node)
        if not name:
            return
        sq = self._current_qname()
        qualified = sq + "." + name if sq else name
        info = NodeInfo(
            file_id=0, name=name, qualified_name=qualified,
            node_type="variable",
            line_start=_node_line(node), line_end=_node_end_line(node),
            col_offset=_node_col(node),
            parent_node_id=self._current_type_id or 0,
        )
        self._add_node(info)
        self.references.append(ReferenceInfo(
            source_qname=sq, target_name=name, edge_type="write",
            line=_node_line(node),
        ))
        self.name_usages.add(name)
        type_node = None
        if node.type == "declaration_pattern":
            type_node = node.child_by_field_name("type")
            if type_node:
                self._emit_type_read(type_node, sq, _node_line(node))
        for child in node.children:
            if type_node is not None and child == type_node:
                continue
            self._walk(child)

    # ------------------------------------------------------------------
    # is / as / cast expressions  (high priority)
    # ------------------------------------------------------------------

    def _visit_is_expression(self, node: Any) -> None:
        sq = self._current_qname()
        for child in node.children:
            if child.type == "type_pattern":
                type_node = child.child_by_field_name("type")
                if type_node:
                    self._emit_type_read(type_node, sq, _node_line(node))
            self._walk(child)

    def _visit_type_check_expression(self, node: Any) -> None:
        """Handle ``as`` and ``cast`` expressions: ``x as Foo``, ``(Foo)x``."""
        sq = self._current_qname()
        if node.type == "as_expression":
            type_node = node.child_by_field_name("right")
        else:
            type_node = node.child_by_field_name("type")
        if not type_node:
            for child in node.children:
                if child.type in ("identifier", "qualified_name", "generic_name",
                                  "predefined_type", "nullable_type", "array_type", "tuple_type"):
                    type_node = child
                    break
        if type_node:
            self._emit_type_read(type_node, sq, _node_line(node))
        for child in node.children:
            if type_node is not None and child == type_node:
                continue
            self._walk(child)

    # ------------------------------------------------------------------
    # catch clause variable  (high priority)
    # ------------------------------------------------------------------

    def _visit_catch(self, node: Any) -> None:
        sq = self._current_qname()
        decl = (
            node.child_by_field_name("declaration")
            or node.child_by_field_name("catch_declaration")
        )
        if decl is None:
            # Newer grammars keep ``catch_declaration`` as an anonymous child
            for child in node.children:
                if child.type == "catch_declaration":
                    decl = child
                    break
        if decl:
            type_node = decl.child_by_field_name("type")
            name_node = decl.child_by_field_name("name")
            if name_node:
                name = _node_text(name_node)
                if name:
                    qualified = sq + "." + name if sq else name
                    info = NodeInfo(
                        file_id=0, name=name, qualified_name=qualified,
                        node_type="variable",
                        line_start=_node_line(decl), line_end=_node_end_line(decl),
                        col_offset=_node_col(decl),
                        parent_node_id=self._current_type_id or 0,
                    )
                    self._add_node(info)
                    self.references.append(ReferenceInfo(
                        source_qname=sq, target_name=name, edge_type="write",
                        line=_node_line(decl),
                    ))
                    self.name_usages.add(name)
            if type_node:
                self._emit_type_read(type_node, sq, _node_line(decl))
        for child in node.children:
            if decl is not None and child == decl:
                continue
            self._walk(child)

    # ------------------------------------------------------------------
    # foreach loop variable  (high priority)
    # ------------------------------------------------------------------

    def _visit_foreach(self, node: Any) -> None:
        sq = self._current_qname()
        type_node = node.child_by_field_name("type")
        var_node = node.child_by_field_name("left")

        if var_node is None:
            # Fallback for grammars without typed fields: manual paren scan
            in_paren = False
            for child in node.children:
                if child.type == "(":
                    in_paren = True
                    continue
                if not in_paren:
                    continue
                if child.type == "in":
                    break
                txt = _node_text(child)
                if child.type in ("var_keyword",) or txt == "var":
                    if type_node is None:
                        type_node = child
                    continue
                if child.type in ("identifier", "qualified_name", "generic_name",
                                  "predefined_type", "nullable_type", "array_type",
                                  "tuple_type", "implicit_type"):
                    if type_node is None:
                        type_node = child
                    elif var_node is None:
                        var_node = child
                        break

        if var_node:
            name = _node_text(var_node)
            if name:
                qualified = sq + "." + name if sq else name
                info = NodeInfo(
                    file_id=0, name=name, qualified_name=qualified,
                    node_type="variable",
                    line_start=_node_line(var_node), line_end=_node_end_line(var_node),
                    col_offset=_node_col(var_node),
                    parent_node_id=self._current_type_id or 0,
                )
                self._add_node(info)
                self.references.append(ReferenceInfo(
                    source_qname=sq, target_name=name, edge_type="write",
                    line=_node_line(var_node),
                ))
                self.name_usages.add(name)
                if type_node and type_node.type not in ("implicit_type", "var_keyword"):
                    type_name = (
                        _scoped_name(type_node)
                        if type_node.type in ("qualified_name", "generic_name")
                        else _node_text(type_node)
                    )
                    if type_name and type_name != "var":
                        self._var_types[name] = type_name

        if type_node and type_node.type not in ("implicit_type", "var_keyword"):
            self._emit_type_read(type_node, sq, _node_line(node))

        for child in node.children:
            if type_node is not None and child == type_node:
                continue
            self._walk(child)

    # ------------------------------------------------------------------
    # Local function  (medium priority)
    # ------------------------------------------------------------------

    def _visit_local_function(self, node: Any) -> None:
        name_node = node.child_by_field_name("name")
        if not name_node:
            for child in node.children:
                if child.type == "identifier":
                    name_node = child
                    break
        if not name_node:
            for child in node.children:
                self._walk(child)
            return
        name = _node_text(name_node)
        if not name:
            for child in node.children:
                self._walk(child)
            return

        qualified = self._current_qname() + "." + name
        type_ann = self._extract_return_type(node)
        is_async = _has_modifier(node, "async")
        visibility = _extract_visibility(node)

        info = NodeInfo(
            file_id=0, name=name, qualified_name=qualified,
            node_type="method",
            line_start=_node_line(node), line_end=_node_end_line(node),
            col_offset=_node_col(node),
            parent_node_id=self._current_type_id,
            is_async=is_async, type_annotation=type_ann,
            visibility=visibility,
        )
        nid = self._add_node(info)

        self._push_scope(name)
        self._method_scope_depth += 1
        prev_method_id = self._current_method_id
        self._current_method_id = nid
        try:
            body = node.child_by_field_name("body")
            if body:
                self._walk(body)
            else:
                for child in node.children:
                    if child.type in ("modifier", "attribute_list", "type",
                                      "type_parameter_list", "type_parameter_constraints_clause",
                                      "parameter_list", "return_type",
                                      "arrow_expression_clause", "semicolon"):
                        continue
                    self._walk(child)
        finally:
            self._current_method_id = prev_method_id
            self._method_scope_depth -= 1
            self._pop_scope()

    # ------------------------------------------------------------------
    # Element access (indexer)  (medium priority)
    # ------------------------------------------------------------------

    def _visit_element_access(self, node: Any) -> None:
        """Indexer access ``arr[i]`` — reads flow from the walked children.

        ``this[i]`` / ``base[i]`` reference the containing type's own
        indexer (``this[]``); ``obj[i]`` on a typed variable resolves to
        the receiver's ``<type>.this[]`` node (exact qname).
        """
        expr = node.child_by_field_name("expression")
        if expr is not None and expr.child_count == 0:
            etxt = _node_text(expr)
            sq = self._current_qname()
            if etxt in ("this", "base"):
                self.references.append(ReferenceInfo(
                    source_qname=sq, target_name="this[]",
                    edge_type="read", line=_node_line(node),
                ))
                self.name_usages.add("this[]")
            elif expr.type == "identifier":
                for tq in self._match_indexer_types(expr):
                    target = tq + ".this[]"
                    self.references.append(ReferenceInfo(
                        source_qname=sq, target_name=target,
                        edge_type="read", line=_node_line(node),
                    ))
                    self.name_usages.add(target)
        for child in node.children:
            self._walk(child)

    def _match_indexer_types(self, expr: Any) -> list[str]:
        """Resolve which types' indexer an element-access receiver reads.

        ``obj[i]`` binds to the *declared type* of ``obj`` (explicit
        annotation or inferred from ``new`` in the initializer).  Returns
        the matching type qnames; empty when the receiver's type is unknown.
        """
        if not self._type_indexers:
            return []
        if expr.type != "identifier":
            return []
        base_type = self._var_types.get(_node_text(expr), "")
        if not base_type:
            return []
        return [
            tq for tq in self._type_indexers
            if tq.endswith("." + base_type) or tq == base_type
        ]

    # ------------------------------------------------------------------
    # typeof / sizeof / default expressions  (medium priority)
    # ------------------------------------------------------------------

    def _visit_typeof_expression(self, node: Any) -> None:
        sq = self._current_qname()
        type_node = node.child_by_field_name("type") or node.child_by_field_name("name")
        if not type_node:
            for child in node.children:
                if child.type in ("identifier", "qualified_name", "generic_name",
                                  "predefined_type", "nullable_type", "array_type", "tuple_type"):
                    type_node = child
                    break
        if type_node:
            self._emit_type_read(type_node, sq, _node_line(node))
        for child in node.children:
            if type_node is not None and child == type_node:
                continue
            self._walk(child)

    # ------------------------------------------------------------------
    # Identifier read

    def _visit_identifier_read(self, node: Any) -> None:
        # Generic references (Get<int> / List<int>) resolve to their
        # base name — the type-argument list is not a symbol.
        if node.type == "generic_name":
            name = _generic_base_name(node)
        elif node.type == "qualified_name":
            name = _scoped_name(node)
        else:
            name = _node_text(node)
        if not name:
            return

        skip_keywords = frozenset({
            "var", "new", "if", "else", "for", "foreach", "while", "do",
            "switch", "case", "break", "continue", "return", "throw",
            "try", "catch", "finally", "using", "lock", "async", "await",
            "public", "private", "protected", "internal", "static", "readonly",
            "const", "virtual", "override", "abstract", "sealed", "extern",
            "partial", "class", "struct", "interface", "enum", "record",
            "delegate", "event", "namespace", "operator", "sizeof", "typeof",
            "nameof", "is", "as", "in", "out", "ref", "params", "this", "base",
            "null", "true", "false", "void", "int", "long", "short", "byte",
            "float", "double", "decimal", "bool", "char", "string", "object",
            "dynamic", "sbyte", "uint", "ulong", "ushort", "nint", "nuint",
            "get", "set", "init", "add", "remove",
        })

        if name in skip_keywords:
            return

        self.name_usages.add(name)
        sq = self._current_qname()
        self.references.append(ReferenceInfo(
            source_qname=sq,
            target_name=name,
            edge_type="read",
            line=_node_line(node),
        ))

    # ------------------------------------------------------------------
    # Using directives
    # ------------------------------------------------------------------

    def _visit_using(self, node: Any) -> None:
        use_info = self.import_analyzer.analyze_using(node)
        if use_info:
            self.uses.append(use_info)
            # Note: type-resolution logic elsewhere records real identifier
            # uses into self.name_usages.  We deliberately do NOT add the
            # alias/imported names here — declaring ``using Timer = …`` is a
            # directive, not a use of ``Timer``; pre-seeding name_usages
            # would mask genuinely unused aliases.

    # ------------------------------------------------------------------
    # Write / Read ref helpers
    # ------------------------------------------------------------------

    def _emit_write_ref(self, target: Any, sq: str, line: int) -> None:
        if target.type == "identifier":
            name = _node_text(target)
            if name and name not in ("this", "_", "base", "value"):
                self.references.append(ReferenceInfo(
                    source_qname=sq, target_name=name,
                    edge_type="write", line=line,
                ))
                self.name_usages.add(name)
        elif target.type == "member_access_expression":
            name_node = target.child_by_field_name("name")
            member_name = _node_text(name_node) if name_node else ""
            if member_name:
                # Property assignment (obj.Prop = v) is a setter invocation —
                # call edge to the property node, scoped by receiver type.
                expr = target.child_by_field_name("expression")
                if self._match_property_types(expr, member_name):
                    self.references.append(ReferenceInfo(
                        source_qname=sq, target_name=member_name,
                        edge_type="call", line=line,
                    ))
                    self.name_usages.add(member_name)
                    return

                self.references.append(ReferenceInfo(
                    source_qname=sq, target_name=member_name,
                    edge_type="write", line=line,
                ))
                self.name_usages.add(member_name)
        elif target.type in ("tuple_pattern",):
            for child in target.children:
                self._emit_write_ref(child, sq, line)
        elif target.type == "element_access_expression":
            # arr[i] = v writes to the receiver (arr); the index expression
            # is read by the children walk.
            expr = target.child_by_field_name("expression")
            if expr is not None:
                self._emit_write_ref(expr, sq, line)

    def _emit_type_read(self, type_node: Any, sq: str, line: int) -> None:
        """Emit read edges for type references (recursive over composed types).

        Handles identifier / generic_name (including the type-argument list,
        so ``List<User>`` reads both ``List`` and ``User``), qualified_name,
        array_type, nullable_type and tuple_type.
        """
        t = type_node.type
        if t in ("identifier", "generic_name"):
            # Generic type references (List<int>) resolve to their base name.
            name = (
                _generic_base_name(type_node)
                if t == "generic_name"
                else _node_text(type_node)
            )
            if name:
                skip = frozenset({"int", "long", "short", "byte", "float", "double",
                                  "decimal", "bool", "char", "string", "object", "void",
                                  "sbyte", "uint", "ulong", "ushort", "var", "dynamic",
                                  "nint", "nuint"})
                if name not in skip:
                    self.references.append(ReferenceInfo(
                        source_qname=sq, target_name=name,
                        edge_type="read", line=line,
                    ))
                    self.name_usages.add(name)
            if t == "generic_name":
                # Type arguments are type references themselves:
                # List<User> reads User.  ``type_arguments`` is the field in
                # older grammars; current ones use an anonymous
                # type_argument_list.
                args = type_node.child_by_field_name("type_arguments")
                if args is None:
                    for c in type_node.children:
                        if c.type == "type_argument_list":
                            args = c
                            break
                if args is not None:
                    for child in args.children:
                        if child.type in ("identifier", "generic_name", "qualified_name",
                                          "array_type", "nullable_type", "tuple_type",
                                          "predefined_type"):
                            self._emit_type_read(child, sq, line)
        elif t == "qualified_name":
            name = _scoped_name(type_node)
            if name:
                self.references.append(ReferenceInfo(
                    source_qname=sq, target_name=name,
                    edge_type="read", line=line,
                ))
                self.name_usages.add(name.split(".")[-1])
        elif t == "array_type":
            elem = type_node.child_by_field_name("type")
            if elem is not None:
                self._emit_type_read(elem, sq, line)
        elif t == "nullable_type":
            inner = type_node.child_by_field_name("type")
            if inner is not None:
                self._emit_type_read(inner, sq, line)
        elif t == "tuple_type":
            for child in type_node.children:
                if child.type == "tuple_element":
                    etype = child.child_by_field_name("type")
                    if etype is not None:
                        self._emit_type_read(etype, sq, line)
        # predefined_type (int/string/...) is not a user symbol — no edge.

    def _emit_parameter_type_reads(self, params: Any, sq: str, line: int) -> None:
        """Emit a read edge for each parameter's declared type (not its name).

        Also records ``name -> type`` so an indexer/property access on the
        parameter (``c[i]`` / ``c.Prop``) resolves against its declared type.
        """
        for child in params.children:
            if child.type != "parameter":
                continue
            ptype = child.child_by_field_name("type")
            if ptype is not None:
                self._emit_type_read(ptype, sq, line)
                pname_node = child.child_by_field_name("name")
                if pname_node is not None:
                    pname = _node_text(pname_node)
                    if pname:
                        self._var_types[pname] = _node_text(ptype)

    def _emit_signature_type_reads(self, node: Any, sq: str, line: int) -> None:
        """Emit read edges for a member's return type and parameter types.

        The body walk only covers the member body; signature types would
        otherwise receive no inbound edge.
        """
        ret = node.child_by_field_name("returns")
        if ret is None:
            ret = node.child_by_field_name("return_type")
        if ret is None:
            # Operators / conversion operators carry their target type in a
            # ``type`` field (older grammars: an anonymous ``type`` child).
            ret = node.child_by_field_name("type")
        if ret is None:
            for child in node.children:
                if child.type == "type":
                    ret = child
                    break
        if ret is not None:
            self._emit_type_read(ret, sq, line)
        params = node.child_by_field_name("parameters")
        if params is None:
            for child in node.children:
                if child.type == "parameter_list":
                    params = child
                    break
        if params is not None:
            self._emit_parameter_type_reads(params, sq, line)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _add_node(self, node: NodeInfo) -> int:
        if node.node_type == "field" and node.qualified_name:
            if node.qualified_name in self._field_qnames:
                return 0
            self._field_qnames.add(node.qualified_name)
        nid = self._node_id
        self._node_id += 1
        node.id = nid
        self.nodes.append(node)
        return nid

    def _check_explicit_interface(self, node: Any) -> None:
        """Emit inherit edge for ``explicit_interface_specifier`` children."""
        for child in node.children:
            if child.type == "explicit_interface_specifier":
                iface_name = _explicit_interface_name(child)
                if iface_name:
                    sq = self._current_qname()
                    key = (sq, iface_name)
                    if key not in self._explicit_inherits:
                        self._explicit_inherits.add(key)
                        self.references.append(ReferenceInfo(
                            source_qname=sq,
                            target_name=iface_name,
                            edge_type="inherit",
                            line=_node_line(child),
                        ))
                break

    @staticmethod
    def _extract_doc(node: Any) -> str:
        docs: list[str] = []
        parent = node.parent
        if parent:
            for child in parent.children:
                if child == node:
                    break
                if child.type in ("comment", "xml_doc_comment"):
                    txt = _node_text(child).strip()
                    if child.type == "xml_doc_comment":
                        txt = txt.lstrip("///").strip()
                    docs.append(txt)
        result = "\n".join(docs)
        if len(result) > 500:
            result = result[:497] + "..."
        return result

    @staticmethod
    def _check_deprecated(node: Any, doc: str) -> bool:
        combined = doc.lower()
        if "deprecated" in combined or "[obsolete" in combined.lower():
            return True
        for child in node.children:
            if child.type == "attribute_list":
                txt = _node_text(child).lower()
                if "obsolete" in txt:
                    return True
        return False

    @staticmethod
    def _extract_return_type(node: Any) -> str:
        # ``returns`` is the method return-type field in current
        # tree-sitter-c-sharp grammars (``return_type``/``type`` in older
        # ones).
        ret = (node.child_by_field_name("returns")
               or node.child_by_field_name("return_type")
               or node.child_by_field_name("type"))
        if ret:
            return _node_text(ret)
        return ""

    @staticmethod
    def _extract_property_type(node: Any) -> str:
        type_node = node.child_by_field_name("type")
        if type_node:
            return _node_text(type_node)
        return ""
