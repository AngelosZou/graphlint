# -*- coding: utf-8 -*-
"""Tree-sitter CST visitor — traverses the C++ concrete syntax tree to extract
nodes (symbol definitions), structured references (edges), and imports.

Approach A: static member-call resolution
=========================================
1. Collect ``{var_name: type_name}`` from ``declaration`` nodes
   (type_identifier + plain identifier).
2. ``player.update()`` (field_expression) → resolve ``Player`` class →
   method ``update`` → call edge.
   If unclear (std::, unknown/pointer) → conservative read edge, no error.
3. Inheritance: ``class Player : public Entity`` → inheritance edge;
   child resolves to parent method by walking ``base_class_clause``.
4. NO dynamic dispatch / vtable / RTTI / template instantiation. Static only.
"""

from __future__ import annotations

from typing import Any

from graphlint.analyzer._types import NodeInfo, ReferenceInfo
from graphlint.analyzer.language.cpp.constants import (
    _CST_TYPE_TO_NODE_TYPE,
    _TYPE_MEMBER_NODE_TYPES,
)
from graphlint.analyzer.language.cpp.imports import (
    CppImportAnalyzer,
    IncludeInfo,
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
    """Extract dotted name from a qualified_identifier or identifier node."""
    if node.type == "qualified_identifier":
        parts = []
        for child in node.children:
            if child.type in ("identifier", "namespace_identifier",
                              "operator_name"):
                parts.append(_node_text(child))
            elif child.type == "qualified_identifier":
                inner = _scoped_name(child)
                if inner:
                    parts.append(inner)
        return "::".join(parts)
    if node.type == "identifier":
        return _node_text(node)
    if node.type in ("template_function", "template_type"):
        return _scoped_name(node) if hasattr(node, "children") else ""
    if node.type == "field_identifier":
        return _node_text(node)
    return ""


def _call_name_from_expr(expr_node: Any) -> str:
    """Extract the callable name from an expression node."""
    if expr_node.type == "identifier":
        return _node_text(expr_node)
    if expr_node.type == "qualified_identifier":
        return _scoped_name(expr_node)
    if expr_node.type == "field_expression":
        field = expr_node.child_by_field_name("field")
        if field:
            return _node_text(field)
        # Fallback: walk children for field_identifier
        for child in expr_node.children:
            if child.type == "field_identifier":
                return _node_text(child)
    if expr_node.type == "template_function":
        name_node = expr_node.child_by_field_name("name")
        if name_node:
            return _node_text(name_node)
    return ""


def _dotted_call_name(expr_node: Any) -> str:
    """Full dotted name of a callable expression (e.g. ``obj.method``).
    Used for ``function_call:`` entry-rule matching.
    """
    if expr_node.type == "field_expression":
        field = expr_node.child_by_field_name("field")
        arg = expr_node.child_by_field_name("argument")
        base = _dotted_call_name(arg) if arg is not None else ""
        nm = _node_text(field) if field else ""
        if base and nm:
            return base + "." + nm
        return nm
    return _call_name_from_expr(expr_node)


def _extract_base_types(node: Any) -> list[str]:
    """Extract base class names from a class_specifier via base_class_clause."""
    bases: list[str] = []
    for child in node.children:
        if child.type == "base_class_clause":
            for grandchild in child.children:
                if grandchild.type in ("identifier", "qualified_identifier",
                                        "template_type", "type_identifier"):
                    bases.append(_scoped_name(grandchild) or _node_text(grandchild))
    return bases


def _extract_type_annotation(decl: Any) -> str:
    """Extract the type from a declaration node."""
    type_node = decl.child_by_field_name("type")
    if type_node:
        if type_node.type == "qualified_identifier":
            return _scoped_name(type_node)
        return _node_text(type_node)
    return ""


def _strip_template_prefix(qualified: str) -> str:
    """Strip template_ prefix from namespace-like qualified names."""
    # tree-sitter-cpp nests templates as template_declaration →
    # function_definition; the qualified name shouldn't carry a
    # "template_" segment.
    parts = qualified.split(".")
    clean = []
    for p in parts:
        if p.startswith("template_"):
            p = p[len("template_"):]
        if p:
            clean.append(p)
    return ".".join(clean)


def _is_type_like(node_type: str) -> bool:
    """Check if a node type represents a type declaration that has methods."""
    return node_type in ("class", "struct", "union")


class CppVisitor:
    """Walks a tree-sitter CST of C++ and extracts nodes, references,
    and imports with Approach A static member-call resolution."""

    def __init__(
        self,
        module_qname: str,
        file_path: str,
        import_analyzer: CppImportAnalyzer,
    ) -> None:
        self.module_qname = module_qname
        self.file_path = file_path
        self.import_analyzer = import_analyzer

        self.nodes: list[NodeInfo] = []
        self.references: list[ReferenceInfo] = []
        self.name_usages: set[str] = set()
        self.uses: list[IncludeInfo] = []
        self.warnings: list[Any] = []

        self._context: list[str] = []
        self._current_type_id: int = 0
        self._current_type_qname: str = ""
        self._current_base_types: list[str] = []
        self._node_id: int = 1
        self._field_qnames: set[str] = set()

        # Variable → type tracking (Approach A).  Kept scope-aware so that
        # locals do not leak across methods and a local may shadow a field:
        #  - ``_field_var_types``: class members (visible to every method).
        #  - ``_local_var_types``: innermost-first stack of block scopes.
        #  - ``_global_var_types``: file-scope declarations.
        self._field_var_types: dict[str, str] = {}
        self._local_var_types: list[dict[str, str]] = []
        self._global_var_types: dict[str, str] = {}

        # Depth of enclosing function/method bodies (distinguishing fields
        # from locals).
        self._method_scope_depth: int = 0

        # Node id of the innermost enclosing function/method.
        self._current_method_id: int = 0

        # Methods per type (type_qname → set of method names), populated
        # during CST walk and used by Approach A resolution.
        self._type_methods: dict[str, set[str]] = {}

        # Inheritance edges (child_type_qname → [parent_type_name, ...]).
        # Collected as we walk and used for parent-method resolution.
        self._inherit_edges: dict[str, list[str]] = {}

    def _current_qname(self) -> str:
        return ".".join(self._context) if self._context else ""

    def _push_scope(self, name: str) -> None:
        self._context.append(name)

    def _pop_scope(self) -> None:
        if self._context:
            self._context.pop()

    def _push_local_scope(self) -> None:
        self._local_var_types.append({})

    def _pop_local_scope(self) -> None:
        if self._local_var_types:
            self._local_var_types.pop()

    def _register_var_type(self, name: str, type_name: str, *, is_field: bool = False) -> None:
        """Track *name → type_name* at the narrowest applicable scope.

        Class fields go to the persistent field map (available to every
        method), locals to the innermost enclosing block scope, and
        file-scope names to ``_global_var_types``.
        """
        if not name or not type_name:
            return
        if is_field:
            self._field_var_types[name] = type_name
        elif self._local_var_types:
            self._local_var_types[-1][name] = type_name
        else:
            self._global_var_types[name] = type_name

    def _lookup_var_type(self, name: str) -> str:
        """Nearest-scope receiver type lookup: innermost block, outer
        blocks, then class fields, then file-scope names."""
        for scope in reversed(self._local_var_types):
            if name in scope:
                return scope[name]
        if name in self._field_var_types:
            return self._field_var_types[name]
        return self._global_var_types.get(name, "")

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def visit(self, tree: Any) -> None:
        root = tree.root_node if hasattr(tree, "root_node") else tree
        # Push module name as initial scope so qualified names include it
        if self.module_qname:
            for part in self.module_qname.split("."):
                if part:
                    self._push_scope(part)
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

        if ntype == "translation_unit":
            for child in node.children:
                self._walk(child)

        elif ntype == "namespace_definition":
            self._visit_namespace(node)

        elif ntype == "template_declaration":
            self._visit_template_declaration(node)

        elif ntype in _CST_TYPE_TO_NODE_TYPE:
            self._visit_type_declaration(node, ntype)

        elif ntype in _TYPE_MEMBER_NODE_TYPES:
            self._visit_member(node, ntype)

        elif ntype == "preproc_include":
            self._visit_include(node)

        elif ntype == "declaration":
            self._visit_declaration(node)

        elif ntype == "call_expression":
            self._visit_call(node)

        elif ntype == "field_expression":
            self._visit_field_expression(node)

        elif ntype == "assignment_expression":
            self._visit_assignment(node)

        elif ntype == "new_expression":
            self._visit_new_expression(node)

        elif ntype == "delete_expression":
            self._visit_delete_expression(node)

        elif ntype == "compound_statement":
            # A block introduces a local-variable scope so that inner locals
            # do not leak into the outer (function/file) scope.
            self._push_local_scope()
            try:
                for child in node.children:
                    self._walk(child)
            finally:
                self._pop_local_scope()

        elif ntype == "preproc_def":
            self._visit_preproc_def(node)

        elif ntype == "preproc_function_def":
            self._visit_preproc_def(node)

        else:
            for child in node.children:
                self._walk(child)

    # ------------------------------------------------------------------
    # Namespace
    # ------------------------------------------------------------------

    def _visit_namespace(self, node: Any) -> None:
        name_node = node.child_by_field_name("name")
        name = _scoped_name(name_node) if name_node else ""
        if name_node and not name:
            name = _node_text(name_node)
        body = node.child_by_field_name("body")

        if not name:
            # Anonymous ``namespace { ... }``: there is no namespace to push,
            # but the body still declares names in the enclosing scope and must
            # be walked (a type/function inside it is a real symbol).
            if body:
                self._walk(body)
            else:
                for child in node.children:
                    self._walk(child)
            return

        self._push_scope(name)
        if body:
            self._walk(body)
        else:
            for child in node.children:
                self._walk(child)
        self._pop_scope()

    # ------------------------------------------------------------------
    # Template declaration — wraps templated types/functions
    # ------------------------------------------------------------------

    def _visit_template_declaration(self, node: Any) -> None:
        """Walk children; template functions/types are handled by their own
        handlers.  We push a synthetic scope to avoid naming conflicts but
        strip it from qualified names later."""
        self._push_scope("template_")
        for child in node.children:
            if child.type in ("template_parameter_list", "template", "typename",
                              "class", "auto"):
                continue
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
        # Strip any template_ prefix from enclosing scopes
        qualified = _strip_template_prefix(qualified)
        node_type = _CST_TYPE_TO_NODE_TYPE.get(ntype, "class")
        visibility = ""  # C++ doesn't have access modifiers on the type itself

        info = NodeInfo(
            file_id=0,
            name=name,
            qualified_name=qualified,
            node_type=node_type,
            line_start=_node_line(node),
            line_end=_node_end_line(node),
            col_offset=_node_col(node),
            parent_node_id=self._current_type_id,
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
            # Record inheritance for Approach A resolution
            if qualified not in self._inherit_edges:
                self._inherit_edges[qualified] = []
            if bt not in self._inherit_edges[qualified]:
                self._inherit_edges[qualified].append(bt)

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
                if child.type in ("base_class_clause", "template_parameter_list",
                                  "template_parameter", "class", "struct",
                                  "enum", "union", "semicolon", "{", "}"):
                    continue
                self._walk(child)

        self._pop_scope()
        self._current_type_id = prev_type_id
        self._current_type_qname = prev_type_qname
        self._current_base_types = prev_base_types

    # ------------------------------------------------------------------
    # Member declarations (methods, fields)
    # ------------------------------------------------------------------

    def _visit_member(self, node: Any, ntype: str) -> None:
        if ntype == "field_declaration":
            self._visit_field_declaration(node)
            return
        if ntype == "function_definition":
            # Only treat as method if inside a type declaration
            is_method = self._current_type_id != 0
            self._visit_function_definition(node, is_method=is_method)
            return

    def _visit_field_declaration(self, node: Any) -> None:
        sq = _strip_template_prefix(self._current_qname())
        # Walk children to find declarator identifiers
        type_ann = _extract_type_annotation(node)

        # Check for function_declarator (method declaration without body)
        # — these are definitions, not uses.
        for child in node.children:
            if child.type == "function_declarator":
                self._visit_method_declaration(node, sq)
                return

        for child in node.children:
            name_node = None
            if child.type == "field_declarator":
                name_node = child.child_by_field_name("declarator")
                if name_node is None:
                    # The field_declarator itself may be an identifier
                    for gc in child.children:
                        if gc.type == "identifier":
                            name_node = gc
                            break
            elif child.type == "field_identifier":
                name_node = child

            if name_node is None:
                continue
            if name_node.type == "pointer_declarator":
                # Skip pointer declarators for name resolution;
                # find the inner identifier.
                for gc in name_node.children:
                    if gc.type == "field_identifier":
                        name_node = gc
                        break
            if name_node.type not in ("identifier", "field_identifier"):
                continue
            name = _node_text(name_node)
            if not name:
                continue

            qualified = sq + "." + name if sq else name
            info = NodeInfo(
                file_id=0,
                name=name,
                qualified_name=qualified,
                node_type="field",
                line_start=_node_line(child),
                line_end=_node_end_line(child),
                col_offset=_node_col(child),
                parent_node_id=self._current_type_id,
                type_annotation=type_ann,
            )
            self._add_node(info)

            # Write edge: the type writes to this field
            self.references.append(ReferenceInfo(
                source_qname=sq,
                target_name=name,
                edge_type="write",
                line=_node_line(child),
            ))

            # Approach A: register field's type for receiver resolution
            if type_ann:
                self._register_var_type(name, type_ann, is_field=True)

            # Walk initializer
            value_node = (
                child.child_by_field_name("value")
                or child.child_by_field_name("default_value")
            )
            if value_node is not None:
                self._walk(value_node)
            else:
                for gc in child.children:
                    if gc.type in ("=", "semicolon", ","):
                        continue
                    if gc == name_node or gc.type in ("pointer_declarator",
                                                        "array_declarator"):
                        continue
                    self._walk(gc)

        # Read edge for the type annotation
        if type_ann:
            self._emit_type_read_name(type_ann, sq, _node_line(node))

    def _visit_method_declaration(self, node: Any, sq: str) -> None:
        """Handle a field_declaration with a function_declarator (method
        without a body — declaration only, skipped as per spec)."""
        for child in node.children:
            if child.type == "function_declarator":
                name_node = child.child_by_field_name("declarator")
                if name_node is None:
                    for gc in child.children:
                        if gc.type == "field_identifier":
                            name_node = gc
                            break
                        if gc.type == "qualified_identifier":
                            name_node = gc
                            break
                if name_node is None:
                    continue
                name = _node_text(name_node)
                if not name:
                    continue

                # Declaration-only methods have no body → no node emitted
                # (per spec: "method without body = no node").
                # But we still emit parameter type reads.
                line = _node_line(child)
                params = child.child_by_field_name("parameters")
                if params is not None:
                    self._emit_parameter_type_reads(params, sq, line)
                return

    def _visit_function_definition(self, node: Any, is_method: bool = False) -> None:
        """Handle a function_definition — either a top-level function or a
        class method."""
        declarator = node.child_by_field_name("declarator")
        if declarator is None:
            for child in node.children:
                if child.type == "function_declarator":
                    declarator = child
                    break
        if declarator is None:
            return

        name_node = declarator.child_by_field_name("declarator")
        if name_node is None:
            for child in declarator.children:
                if child.type in ("identifier", "field_identifier",
                                  "qualified_identifier"):
                    name_node = child
                    break
        if name_node is None:
            return

        name = (
            _scoped_name(name_node)
            if name_node.type == "qualified_identifier"
            else _node_text(name_node)
        )
        if not name:
            return

        # Out-of-class member definitions: `void A::f() {}` at module scope
        # carries a `::`-qualified declarator. Re-open the owning class scope
        # chain so the member is rooted under its class (nested classes walk
        # every `::` segment) instead of being emitted as a free function.
        if not is_method and "::" in name and "(" not in name:
            method_name = name.rsplit("::", 1)[-1]
            scope_chain = name.rsplit("::", 1)[0]
            scope_parts = [p for p in scope_chain.split("::") if p]
            sq = ".".join(self._context + scope_parts) if self._context else ".".join(scope_parts)
            qualified = sq + "." + method_name if sq else method_name
            is_method = True
            node_name = method_name
        else:
            sq = self._current_qname()
            qualified = sq + "." + name if sq else name
            node_name = name

        # Destructors / operator overloads are excluded from Approach A method
        # resolution (they are never resolved via an explicit member call).
        # The "~" and "operator" forms are still special so their nodes are
        # recognized via CppAdapter.is_special_name (and not reported as
        # dead code); a plain method follows normal handling.
        is_ctor_or_dtor = node_name.startswith(("~", "operator"))

        type_qname = (
            self._current_type_qname
            if is_method and "::" not in name
            else sq.lstrip(".")
        )

        qualified = _strip_template_prefix(qualified)

        if is_method and not is_ctor_or_dtor:
            # Register method for Approach A resolution
            tq = type_qname
            if tq:
                if tq not in self._type_methods:
                    self._type_methods[tq] = set()
                self._type_methods[tq].add(node_name)

        node_type_val = "method" if is_method else "function"
        parent_id = self._current_type_id if is_method else 0

        type_ann = self._extract_return_type(node)
        is_deprecated = self._check_deprecated(node)

        info = NodeInfo(
            file_id=0,
            name=node_name,
            qualified_name=qualified,
            node_type=node_type_val,
            line_start=_node_line(node),
            line_end=_node_end_line(node),
            col_offset=_node_col(node),
            parent_node_id=parent_id,
            type_annotation=type_ann,
            is_deprecated=is_deprecated,
        )
        nid = self._add_node(info)

        self._push_scope(node_name)
        self._method_scope_depth += 1
        prev_method_id = self._current_method_id
        self._current_method_id = nid
        self._push_local_scope()
        self._emit_signature_type_reads(node, qualified, _node_line(node))
        try:
            body = node.child_by_field_name("body")
            if body:
                self._walk(body)
            else:
                for child in node.children:
                    if child == declarator:
                        continue
                    if child.type in ("type", "virtual", "static", "const",
                                      "override", "final", "noexcept",
                                      "throw", "specifier", "storage_class_specifier",
                                      "attribute_specifier",
                                      "trailing_return_type", "semicolon"):
                        continue
                    self._walk(child)
        finally:
            self._current_method_id = prev_method_id
            self._method_scope_depth -= 1
            self._pop_scope()
            self._pop_local_scope()

    # ------------------------------------------------------------------
    # Variable declarations
    # ------------------------------------------------------------------

    def _visit_declaration(self, node: Any) -> None:
        sq = self._current_qname()

        # Skip declarations that are actually function declarations
        # (they contain a function_declarator but no body)
        has_function_declarator = False
        for child in node.children:
            if child.type == "function_declarator":
                has_function_declarator = True
                break

        is_field = self._current_type_id != 0 and self._method_scope_depth == 0
        node_type_val = "field" if is_field else "variable"
        parent_id = (
            self._current_type_id
            if is_field
            else (self._current_method_id or self._current_type_id or 0)
        )

        type_ann = _extract_type_annotation(node)

        # Simple declarations without an initializer: `Player player;`
        # (a bare type_identifier/type followed by a plain identifier). Handle
        # these directly so the variable is emitted and its type registered
        # for Approach A receiver resolution.
        if not any(c.type == "init_declarator" for c in node.children):
            if has_function_declarator:
                # A function declaration (prototype) without a body is
                # non-local; nothing to register here.
                pass
            else:
                bare_type = _extract_type_annotation(node)
                bare_name = None
                for c in node.children:
                    if c.type in ("identifier", "field_identifier"):
                        bare_name = c
                        break
                    if c.type in ("pointer_declarator", "reference_declarator"):
                        for gc in c.children:
                            if gc.type in ("identifier", "field_identifier"):
                                bare_name = gc
                                break
                        if bare_name is not None:
                            break
                if bare_name is not None and bare_type:
                    name = _node_text(bare_name)
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
                        type_annotation=bare_type,
                    )
                    self._add_node(info)
                    self.references.append(ReferenceInfo(
                        source_qname=sq,
                        target_name=name,
                        edge_type="write",
                        line=_node_line(node),
                    ))
                    self._register_var_type(name, bare_type, is_field=is_field)
                    self._emit_type_read_name(bare_type, sq, _node_line(node))

        for child in node.children:
            if child.type == "init_declarator":
                decl = child.child_by_field_name("declarator")
                if decl is None:
                    for gc in child.children:
                        if gc.type in ("identifier", "qualified_identifier",
                                        "pointer_declarator", "reference_declarator"):
                            decl = gc

                if decl is None:
                    continue

                # Resolve through pointer/reference declarators
                inner_name_node = decl
                if inner_name_node.type == "pointer_declarator":
                    for gc in inner_name_node.children:
                        if gc.type == "identifier":
                            inner_name_node = gc
                            break
                if inner_name_node.type != "identifier":
                    continue

                name = _node_text(inner_name_node)
                if not name:
                    continue

                if has_function_declarator:
                    # This is a forward declaration, skip
                    continue

                qualified = sq + "." + name if sq else name
                info = NodeInfo(
                    file_id=0,
                    name=name,
                    qualified_name=qualified,
                    node_type=node_type_val,
                    line_start=_node_line(child),
                    line_end=_node_end_line(child),
                    col_offset=_node_col(child),
                    parent_node_id=parent_id,
                    type_annotation=type_ann,
                )
                self._add_node(info)

                # Write edge
                self.references.append(ReferenceInfo(
                    source_qname=sq,
                    target_name=name,
                    edge_type="write",
                    line=_node_line(child),
                ))

                # Approach A: register variable's type
                if type_ann:
                    self._register_var_type(name, type_ann, is_field=is_field)

                # Walk initializer
                value_node = child.child_by_field_name("value")
                if value_node is not None:
                    self._walk(value_node)
                else:
                    for gc in child.children:
                        if gc.type in ("=", "semicolon", ","):
                            continue
                        if gc == decl:
                            continue
                        self._walk(gc)

        # Read edge for the type annotation
        if type_ann:
            self._emit_type_read_name(type_ann, sq, _node_line(node))

    # ------------------------------------------------------------------
    # Call expressions
    # ------------------------------------------------------------------

    def _visit_call(self, node: Any) -> None:
        func = node.child_by_field_name("function")
        if func and func.type == "field_expression":
            # Approach A member call: dispatch the receiver/member through
            # field-expression resolution so it emits a call edge via the
            # receiver's known type (falling back to a conservative edge
            # when the type is unknown).  ``is_arrow`` distinguishes a ``->``
            # access (receiver is a pointer to the resolved type) from a ``.``
            # access and drives the method lookup.
            operator_node = func.child_by_field_name("operator")
            is_arrow = operator_node is not None and _node_text(operator_node) == "->"
            self._visit_field_expression(func, is_arrow=is_arrow)
        elif func:
            cname = _call_name_from_expr(func)
            if cname:
                sq = self._current_qname()
                self.references.append(ReferenceInfo(
                    source_qname=sq,
                    target_name=cname,
                    edge_type="call",
                    line=_node_line(node),
                ))
                self.name_usages.add(cname.split("::")[-1])
                # Also emit the full dotted name for entry rules
                dotted = _dotted_call_name(func)
                if dotted and dotted != cname:
                    self.references.append(ReferenceInfo(
                        source_qname=sq,
                        target_name=dotted,
                        edge_type="call",
                        line=_node_line(node),
                    ))

        for child in node.children:
            if child == func:
                continue
            self._walk(child)

    # ------------------------------------------------------------------
    # Field expression — Approach A resolution
    # ------------------------------------------------------------------

    def _visit_field_expression(self, node: Any, is_arrow: bool | None = None) -> None:
        """Handle ``obj.member`` / ``obj->member``.

        Approach A:
        - If receiver (obj) has a known type → resolve to method → call edge
        - If receiver is std::*, unknown pointer → conservative read edge
        - Walk parent inheritance chain to find the method

        *is_arrow* distinguishes ``->`` (receiver is a pointer to the resolved
        type) from ``.`` (receiver is the value); it is supplied by the caller
        (call expressions) and computed here for standalone field expressions.
        """
        argument = node.child_by_field_name("argument")
        field_node = node.child_by_field_name("field")
        operator_node = node.child_by_field_name("operator")

        # Determine access type: . or ->
        if is_arrow is None:
            is_arrow = False
            if operator_node is not None:
                is_arrow = _node_text(operator_node) == "->"

        member_name = _node_text(field_node) if field_node else ""
        for child in node.children:
            if child.type == "field_identifier":
                member_name = _node_text(child)
                break

        if not member_name:
            for child in node.children:
                self._walk(child)
            return

        sq = self._current_qname()

        # Try Approach A resolution.  ``is_arrow`` (a ``->`` access) means the
        # receiver is a pointer to the resolved type; a ``.`` access resolves
        # against the value type directly.  Either way the method is looked up
        # on the receiver's (pointee/value) type, falling back to a
        # conservative edge when the type is unknown.
        if argument is not None and argument.type == "identifier":
            receiver_name = _node_text(argument)
            type_name = self._lookup_var_type(receiver_name)

            # Reading the receiver is itself a read of the variable (e.g.
            # ``obj`` in ``obj.update()``), alongside the member edge below.
            self.references.append(ReferenceInfo(
                source_qname=sq,
                target_name=receiver_name,
                edge_type="read",
                line=_node_line(node),
            ))
            self.name_usages.add(receiver_name)

            if type_name and not type_name.startswith("std::"):
                # Check if the target method exists on the type or its parents
                resolved = self._resolve_method(type_name, member_name)
                if resolved:
                    self.references.append(ReferenceInfo(
                        source_qname=sq,
                        target_name=resolved + "." + member_name,
                        edge_type="call",
                        line=_node_line(node),
                    ))
                    self.name_usages.add(member_name)
                else:
                    # Method not found — conservative read edge.  For a
                    # ``::``-qualified receiver (e.g. ``engine::Service``) emit
                    # the best-effort module-qualified member target too so a
                    # same-named class in another module resolves to its own
                    # method.
                    self.references.append(ReferenceInfo(
                        source_qname=sq,
                        target_name=member_name,
                        edge_type="read",
                        line=_node_line(node),
                    ))
                    self.name_usages.add(member_name)
                    qtarget = self._qualified_member_target(type_name, member_name)
                    if qtarget:
                        self.references.append(ReferenceInfo(
                            source_qname=sq,
                            target_name=qtarget,
                            edge_type="read",
                            line=_node_line(node),
                        ))
                        self.name_usages.add(qtarget.rsplit(".", 1)[-1])
            elif is_arrow:
                # Arrow with a registered pointer type still resolves the
                # pointee's method; a genuinely unknown receiver → read edge.
                self.references.append(ReferenceInfo(
                    source_qname=sq,
                    target_name=member_name,
                    edge_type="read",
                    line=_node_line(node),
                ))
                self.name_usages.add(member_name)
            else:
                # std:: or unknown/pointer → conservative read edge
                self.references.append(ReferenceInfo(
                    source_qname=sq,
                    target_name=member_name,
                    edge_type="read",
                    line=_node_line(node),
                ))
                self.name_usages.add(member_name)
        else:
            # Complex receiver (e.g., getPlayer().update()) —
            # conservative read edge
            self.references.append(ReferenceInfo(
                source_qname=sq,
                target_name=member_name,
                edge_type="read",
                line=_node_line(node),
            ))
            self.name_usages.add(member_name)

        for child in node.children:
            self._walk(child)

    def _resolve_method(self, type_name: str, method_name: str) -> str | None:
        """Walk the inheritance chain to find a type that declares
        *method_name*. Returns the type qname that owns it, or None."""
        # Search in all known types
        for tq, methods in self._type_methods.items():
            if method_name not in methods:
                continue
            # Check if this type matches or is an ancestor
            if tq.endswith("." + type_name) or tq == type_name:
                return tq

        # Walk inherited types
        for tq in self._type_methods:
            if method_name in self._type_methods[tq]:
                # Check if *type_name* inherits from *tq*
                if self._inherits_from(type_name, tq):
                    return tq

        return None

    def _qualified_member_target(self, type_name: str, member_name: str) -> str:
        """Best-effort qname for the *member* of a ``::``-qualified receiver.

        ``engine::Service`` normalizes to ``engine.Service``; the class
        defined in ``engine/Service.h`` parses as ``engine.Service.Service``,
        so ``engine::Service().run()`` yields ``engine.Service.Service.run``.
        With same-named classes in different modules the constructed target is
        unique, unlike the bare ``run`` edge.
        """
        if "::" not in type_name or type_name.startswith("std::"):
            return ""
        cleaned = type_name.rstrip("*&").replace("::", ".")
        parts = [p for p in cleaned.split(".") if p]
        if len(parts) < 2:
            return ""
        return f"{cleaned}.{parts[-1]}.{member_name}"

    def _inherits_from(self, child_type: str, parent_type: str) -> bool:
        """Check if *child_type* (directly or transitively) inherits from
        *parent_type*."""
        direct_bases = self._inherit_edges.get(child_type, [])
        if parent_type in direct_bases or any(
            direct_bases and parent_type in direct_bases
        ):
            return True
        # Walk transitively (simple name match — not full qname, which is a
        # limitation of this static approach)
        for base in direct_bases:
            if self._inherits_from(base, parent_type):
                return True
        return False

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
    # new / delete expressions
    # ------------------------------------------------------------------

    def _visit_new_expression(self, node: Any) -> None:
        """Handle ``new Foo(...)`` — read edge to the type name."""
        type_node = node.child_by_field_name("type")
        if type_node:
            sq = self._current_qname()
            type_name = _scoped_name(type_node) or _node_text(type_node)
            if type_name:
                self.references.append(ReferenceInfo(
                    source_qname=sq,
                    target_name=type_name,
                    edge_type="read",
                    line=_node_line(node),
                ))
                self.name_usages.add(type_name.split("::")[-1])
        for child in node.children:
            self._walk(child)

    def _visit_delete_expression(self, node: Any) -> None:
        for child in node.children:
            self._walk(child)

    # ------------------------------------------------------------------
    # #include and #define
    # ------------------------------------------------------------------

    def _visit_include(self, node: Any) -> None:
        include_info = self.import_analyzer.analyze_include(node)
        if include_info and not include_info.is_system:
            self.uses.append(include_info)

    def _visit_preproc_def(self, node: Any) -> None:
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        name = _node_text(name_node)
        if not name:
            return
        sq = self._current_qname()
        qualified = sq + "." + name if sq else name
        info = NodeInfo(
            file_id=0,
            name=name,
            qualified_name=qualified,
            node_type="macro",
            line_start=_node_line(node),
            line_end=_node_end_line(node),
            col_offset=_node_col(node),
            parent_node_id=0,
        )
        self._add_node(info)

    # ------------------------------------------------------------------
    # Write / Read ref helpers
    # ------------------------------------------------------------------

    def _emit_write_ref(self, target: Any, sq: str, line: int) -> None:
        if target.type == "identifier":
            name = _node_text(target)
            if name and name not in ("this", "_", "nullptr", "NULL"):
                self.references.append(ReferenceInfo(
                    source_qname=sq, target_name=name,
                    edge_type="write", line=line,
                ))
                self.name_usages.add(name)
        elif target.type == "field_expression":
            field_node = target.child_by_field_name("field")
            member_name = _node_text(field_node) if field_node else ""
            if member_name:
                self.references.append(ReferenceInfo(
                    source_qname=sq, target_name=member_name,
                    edge_type="write", line=line,
                ))
                self.name_usages.add(member_name)
        elif target.type == "subscript_expression":
            self.references.append(ReferenceInfo(
                source_qname=sq, target_name="subscript",
                edge_type="write", line=line,
            ))

    def _emit_type_read_name(self, type_name: str, sq: str, line: int) -> None:
        """Emit a read edge for a type name string."""
        skip = frozenset({"int", "long", "short", "char", "float", "double",
                           "bool", "void", "unsigned", "signed", "auto",
                           "size_t", "wchar_t", "char16_t", "char32_t",
                           "nullptr_t", "string", "vector", "map", "set",
                           "list", "queue", "stack", "deque", "array",
                           "unique_ptr", "shared_ptr", "weak_ptr",
                           "optional", "variant"})
        if type_name and type_name not in skip and not type_name.startswith("std::"):
            self.references.append(ReferenceInfo(
                source_qname=sq, target_name=type_name,
                edge_type="read", line=line,
            ))
            self.name_usages.add(type_name.split("::")[-1])
            # A ``::``-qualified type (e.g. ``engine::Service``) read: also
            # emit the best-effort qname of the class that would define it
            # (``engine.Service.Service`` from ``engine/Service.h``), so the
            # read can resolve to the right header in cross-file graphs.
            if "::" in type_name:
                normalized = type_name.replace("::", ".").strip(".*&")
                parts = [p for p in normalized.split(".") if p]
                if len(parts) >= 2:
                    constructed = f"{normalized}.{parts[-1]}"
                    self.references.append(ReferenceInfo(
                        source_qname=sq, target_name=constructed,
                        edge_type="read", line=line,
                    ))
                    self.name_usages.add(parts[-1])

    def _emit_parameter_type_reads(self, params: Any, sq: str, line: int) -> None:
        """Emit read edges for each parameter's declared type."""
        for child in params.children:
            if child.type != "parameter_declaration":
                continue
            ptype = child.child_by_field_name("type")
            if ptype is not None:
                type_name = _scoped_name(ptype) or _node_text(ptype)
                if type_name:
                    self._emit_type_read_name(type_name, sq, line)
                pname_node = child.child_by_field_name("declarator")
                if pname_node is not None:
                    pname = _node_text(pname_node)
                    if pname and type_name:
                        self._register_var_type(pname, type_name)

    def _emit_signature_type_reads(self, node: Any, sq: str, line: int) -> None:
        """Emit read edges for a function's return type and parameter types."""
        ret = node.child_by_field_name("type")
        if ret is not None:
            type_name = _scoped_name(ret) or _node_text(ret)
            if type_name:
                self._emit_type_read_name(type_name, sq, line)
        params = None
        declarator = node.child_by_field_name("declarator")
        if declarator is None:
            for child in node.children:
                if child.type == "function_declarator":
                    declarator = child
                    break
        if declarator is not None:
            params = declarator.child_by_field_name("parameters")
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

    @staticmethod
    def _extract_return_type(node: Any) -> str:
        ret = node.child_by_field_name("type")
        if ret is not None:
            return _node_text(ret)
        return ""

    @staticmethod
    def _check_deprecated(node: Any) -> bool:
        # C++14 [[deprecated]] attribute
        for child in node.children:
            if child.type == "attribute_specifier":
                for gc in child.children:
                    txt = _node_text(gc)
                    if "deprecated" in txt.lower():
                        return True
        return False
