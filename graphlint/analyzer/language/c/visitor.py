# -*- coding: utf-8 -*-
"""Tree-sitter CST visitor — traverses the C concrete syntax tree to extract
nodes (symbol definitions), structured references (edges), and imports."""

from __future__ import annotations

from typing import Any

from graphlint.analyzer._types import NodeInfo, ReferenceInfo
from graphlint.analyzer.language.c.constants import _CST_TYPE_TO_NODE_TYPE
from graphlint.analyzer.language.c.imports import CImportAnalyzer, CIncludeInfo
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


def _extract_declarator_name(declarator: Any) -> str:
    if declarator is None:
        return ""
    dtype = declarator.type if hasattr(declarator, "type") else ""
    if dtype in ("identifier", "field_identifier"):
        return _node_text(declarator)
    if dtype in (
        "pointer_declarator",
        "function_declarator",
        "array_declarator",
        "parenthesized_declarator",
    ):
        decl = declarator.child_by_field_name("declarator")
        if decl is not None:
            return _extract_declarator_name(decl)
        for child in declarator.children:
            name = _extract_declarator_name(child)
            if name:
                return name
    return ""


def _extract_function_name(func_def: Any) -> str:
    declarator = func_def.child_by_field_name("declarator")
    if declarator is not None:
        return _extract_declarator_name(declarator)
    for child in func_def.children:
        if child.type in (
            "function_declarator",
            "pointer_declarator",
            "array_declarator",
            "parenthesized_declarator",
        ):
            return _extract_declarator_name(child)
    return ""


def _extract_declared_name(declarator: Any) -> str:
    """Extract the declared name from any declarator node, including
    ``type_identifier`` leaves produced in typedef contexts.

    ``typedef void (*callback_t)(void);`` names ``callback_t`` under a
    ``pointer_declarator`` (a ``type_identifier`` leaf); ``int (*fp)(void);``
    names ``fp`` under a ``pointer_declarator`` (an ``identifier`` leaf).
    """
    if declarator is None or not hasattr(declarator, "type"):
        return ""
    dtype = declarator.type
    if dtype in ("identifier", "field_identifier", "type_identifier"):
        return _node_text(declarator)
    if dtype in (
        "pointer_declarator",
        "function_declarator",
        "array_declarator",
        "parenthesized_declarator",
        "init_declarator",
    ):
        decl = declarator.child_by_field_name("declarator")
        if decl is not None:
            name = _extract_declared_name(decl)
            if name:
                return name
        for child in declarator.children:
            name = _extract_declared_name(child)
            if name:
                return name
    return ""


def _extract_type_name(type_def: Any) -> str:
    name_node = type_def.child_by_field_name("name")
    if name_node is not None:
        txt = _node_text(name_node)
        if txt:
            return txt
    for child in type_def.children:
        if child.type == "type_identifier":
            txt = _node_text(child)
            if txt:
                return txt
    declarator = type_def.child_by_field_name("declarator")
    if declarator is not None:
        txt = _extract_declared_name(declarator)
        if txt:
            return txt
    for child in type_def.children:
        if child.type in (
            "function_declarator",
            "pointer_declarator",
            "init_declarator",
            "parenthesized_declarator",
        ):
            txt = _extract_declared_name(child)
            if txt:
                return txt
    return ""


def _declarator_is_function(decl: Any) -> bool:
    """Return True when *decl* resolves to a real function declarator.

    Distinguishes a function declaration from a function-pointer variable:

    * ``int foo(void);``  -> ``function_declarator`` whose declarator field is
      an ``identifier`` (real function).
    * ``int (*fp)(void);`` -> ``function_declarator`` whose declarator field is
      a ``parenthesized_declarator`` (a function-pointer *variable*).

    ``pointer_declarator`` (``int *foo(void);``) and ``init_declarator``
    (``int foo(void) = 0;``) are recursed into via their declarator field.
    """
    if decl is None or not hasattr(decl, "type"):
        return False
    t = decl.type

    if t == "function_declarator":
        declarator = decl.child_by_field_name("declarator")
        if declarator is not None:
            return declarator.type != "parenthesized_declarator"
        for child in decl.children:
            if child.type == "identifier":
                return True
            if child.type == "parenthesized_declarator":
                return False
        return False

    if t in ("pointer_declarator", "init_declarator"):
        return _declarator_is_function(decl.child_by_field_name("declarator"))

    return False


def _extract_macro_name(macro_node: Any) -> str:
    name_node = macro_node.child_by_field_name("name")
    if name_node is not None:
        return _node_text(name_node)
    for child in macro_node.children:
        if child.type in ("identifier", "field_identifier"):
            return _node_text(child)
    return ""


def _extract_field_name(field_decl: Any) -> str:
    for child in field_decl.children:
        if child.type == "field_identifier":
            return _node_text(child)
    for child in field_decl.children:
        if child.type in (
            "pointer_declarator",
            "function_declarator",
            "array_declarator",
            "parenthesized_declarator",
        ):
            name = _extract_declared_name(child)
            if name:
                return name
    return ""


def _extract_call_name(call_expr: Any) -> str:
    func = call_expr.child_by_field_name("function")
    if func is not None:
        if func.type == "identifier":
            return _node_text(func)
        if func.type == "field_expression":
            name_node = func.child_by_field_name("field")
            if name_node is not None:
                return _node_text(name_node)
        if func.type == "parenthesized_expression":
            for child in func.children:
                if child.type == "identifier":
                    return _node_text(child)
    return ""


def _is_on_left_of_assignment(node: Any) -> bool:
    """Check if *node* appears on the LHS of an assignment or update."""
    parent = node.parent
    if parent is None or not hasattr(parent, "type"):
        return False
    ptype = parent.type

    if ptype == "assignment_expression":
        left = parent.child_by_field_name("left")
        if left is not None:
            return _node_contains(left, node)
        return False

    if ptype == "update_expression":
        return True

    if ptype == "init_declarator":
        declarator = parent.child_by_field_name("declarator")
        if declarator is not None:
            return _node_contains(declarator, node)
        for child in parent.children:
            if child.type in ("identifier", "field_identifier",
                              "pointer_declarator", "array_declarator",
                              "function_declarator"):
                if _node_contains(child, node):
                    return True
                return False
        return False

    if ptype == "field_expression":
        field = parent.child_by_field_name("field")
        if field is not None and _node_contains(field, node):
            return _is_on_left_of_assignment(parent)
        return False

    return False


def _node_contains(root: Any, target: Any) -> bool:
    """Walk *root* to check if it contains *target*."""
    if root is None or root == target:
        return root == target
    if not hasattr(root, "children"):
        return False
    for child in root.children:
        if _node_contains(child, target):
            return True
    return False


def _has_static_storage(node: Any) -> bool:
    """Return True when *node* carries a ``static`` storage-class specifier."""
    for child in node.children:
        if child.type == "storage_class_specifier":
            return _node_text(child).strip() == "static"
    return False


def _has_extern_storage(node: Any) -> bool:
    """Return True when *node* carries an ``extern`` storage-class specifier."""
    for child in node.children:
        if child.type == "storage_class_specifier":
            return _node_text(child).strip() == "extern"
    return False


class CVisitor:
    """Walks a tree-sitter CST of C and extracts nodes, references,
    and imports."""

    def __init__(
        self,
        module_qname: str,
        file_path: str,
        import_analyzer: CImportAnalyzer,
    ) -> None:
        self.module_qname = module_qname
        self.file_path = file_path
        self.import_analyzer = import_analyzer

        self.nodes: list[NodeInfo] = []
        self.references: list[ReferenceInfo] = []
        self.name_usages: set[str] = set()
        self.imports: list[CIncludeInfo] = []
        self.warnings: list[Any] = []

        self._context: list[str] = [module_qname] if module_qname else []
        self._current_type_id: int = 0
        self._node_id: int = 1
        self._current_func_id: int = 0

    def _current_qname(self) -> str:
        return ".".join(self._context) if self._context else ""

    def _innermost_scope_name(self) -> str:
        """Simple name of the innermost scope ("" at module level)."""
        return self._context[-1] if self._context else ""

    def _push_scope(self, name: str) -> None:
        self._context.append(name)

    def _pop_scope(self) -> None:
        if self._context:
            self._context.pop()

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

    def _add_node(self, info: NodeInfo) -> int:
        nid = self._node_id
        self._node_id += 1
        info.id = nid
        self.nodes.append(info)
        return nid

    def _walk(self, node: Any) -> None:
        ntype = node.type if hasattr(node, "type") else ""

        if ntype == "translation_unit":
            for child in node.children:
                self._walk(child)

        elif ntype == "function_definition":
            self._visit_function_definition(node)

        elif ntype == "declaration":
            self._visit_top_level_declaration(node)

        elif ntype == "field_declaration":
            self._visit_field_declaration(node)

        elif ntype in ("struct_specifier", "union_specifier", "enum_specifier"):
            self._visit_type_specifier(node)

        elif ntype == "enumerator":
            self._visit_enumerator(node)

        elif ntype == "type_definition":
            self._visit_typedef(node)

        elif ntype in ("preproc_def", "preproc_function_def"):
            self._visit_macro(node)

        elif ntype == "preproc_include":
            self._visit_include(node)

        elif ntype == "call_expression":
            self._visit_call(node)

        elif ntype == "identifier":
            self._visit_identifier(node)

        elif ntype == "field_identifier":
            self._visit_field_identifier_ref(node)

        elif ntype == "type_identifier":
            self._visit_type_identifier_ref(node)

        elif ntype == "field_expression":
            self._visit_field_expression(node)

        elif ntype in (
            "preproc_endif",
            "preproc_params",
            "preproc_arg",
            "preproc_call",
            "comment",
        ):
            pass

        else:
            for child in node.children:
                self._walk(child)

    # ------------------------------------------------------------------
    # Function definition
    # ------------------------------------------------------------------

    def _visit_function_definition(self, node: Any) -> None:
        # NOTE: linkage model. ``static`` functions/variables are marked with
        # visibility="static" so edge building can enforce internal linkage
        # (no cross-file references). Same-named static helpers in different
        # translation units therefore stay independent.
        name = _extract_function_name(node)
        if not name:
            return

        qualified = self._current_qname() + "." + name

        info = NodeInfo(
            file_id=0,
            name=name,
            qualified_name=qualified,
            node_type="function",
            line_start=_node_line(node),
            line_end=_node_end_line(node),
            col_offset=_node_col(node),
            parent_node_id=self._current_type_id,
            visibility="static" if _has_static_storage(node) else "",
        )
        nid = self._add_node(info)

        self._push_scope(name)
        prev_func_id = self._current_func_id
        self._current_func_id = nid

        try:
            body = node.child_by_field_name("body")
            if body:
                self._walk(body)
            else:
                declarator = node.child_by_field_name("declarator")
                for child in node.children:
                    if child == declarator:
                        continue
                    if child.type in (
                        "storage_class_specifier",
                        "type_qualifier",
                        "type",
                        "parameter_list",
                        "attribute_declaration",
                        "attribute_specifier",
                    ):
                        continue
                    self._walk(child)
        finally:
            self._current_func_id = prev_func_id
            self._pop_scope()

    # ------------------------------------------------------------------
    # Top-level declarations (global and local variables)
    # ------------------------------------------------------------------

    # Declarator-shaped children of a `declaration` node. tree-sitter-c only
    # wraps declarators in `init_declarator` when there is an initializer;
    # comma-separated lists (`int foo(void), bar;`, `char *p, q;`) keep the
    # declarators bare.
    _DECLARATOR_TYPES = (
        "init_declarator",
        "pointer_declarator",
        "array_declarator",
        "function_declarator",
        "parenthesized_declarator",
        "identifier",
        "field_identifier",
    )

    def _visit_top_level_declaration(self, node: Any) -> None:
        parent = node.parent
        if parent and hasattr(parent, "type") and parent.type in (
            "struct_specifier", "union_specifier", "enum_specifier",
            "field_declaration_list",
        ):
            for child in node.children:
                if child.type == "field_declaration":
                    self._visit_field_declaration(child)
                else:
                    self._walk(child)
            return

        declarator_children = [
            child for child in node.children
            if child.type in self._DECLARATOR_TYPES
        ]
        if not declarator_children:
            # No declarators at all (e.g. `enum Color { RED, GREEN };` —
            # the enum_specifier child is walked and handles the definition).
            for child in node.children:
                self._walk(child)
            return

        # Process each declarator on its own. A mixed declarator list
        # (`int foo(void), bar;`) must only suppress the function-declaration
        # part — `bar` is a real variable and needs its own node.
        # visibility: "static" (internal linkage), "extern" (declaration of a
        # symbol defined elsewhere — not this library's surface), "" for
        # plain external-linkage definitions.
        is_static = _has_static_storage(node)
        is_extern = _has_extern_storage(node)
        visibility = "static" if is_static else ("extern" if is_extern else "")
        for child in declarator_children:
            if _declarator_is_function(child):
                # Function declaration / prototype — no body, no node
                # (pure-AST dead-code semantics).
                continue
            name = _extract_declared_name(child)
            if not name:
                continue

            qualified = self._current_qname() + "." + name
            info = NodeInfo(
                file_id=0,
                name=name,
                qualified_name=qualified,
                node_type="variable",
                line_start=_node_line(node),
                line_end=_node_end_line(node),
                col_offset=_node_col(node),
                parent_node_id=self._current_type_id,
                visibility=visibility,
            )
            self._add_node(info)

            if child.type == "init_declarator":
                # Walk the initializer value (`int x = foo();` — the call is
                # a use) but not the declarator subtree: reading one's own
                # declaration is not a use.
                declarator = child.child_by_field_name("declarator")
                for sub in child.children:
                    # ``==`` not ``is``: tree-sitter wrappers are fresh per
                    # ``.children`` access.
                    if sub == declarator or sub.type == "=":
                        continue
                    self._walk(sub)

        # Walk the remaining non-declarator children (nested
        # struct/union/enum definitions, typedef-name uses, attributes).
        for child in node.children:
            if child.type in self._DECLARATOR_TYPES:
                continue
            if child.type in (
                "storage_class_specifier", "type_qualifier",
                "type", "primitive_type", "sized_type_specifier",
                "semicolon", ",",
            ):
                continue
            self._walk(child)

    # ------------------------------------------------------------------
    # Field declarations (inside struct/union/enum)
    # ------------------------------------------------------------------

    def _visit_field_declaration(self, node: Any) -> None:
        name = _extract_field_name(node)
        had_name = bool(name)

        if had_name:
            qualified = self._current_qname() + "." + name
            info = NodeInfo(
                file_id=0,
                name=name,
                qualified_name=qualified,
                node_type="field",
                line_start=_node_line(node),
                line_end=_node_end_line(node),
                col_offset=_node_col(node),
                parent_node_id=self._current_type_id,
            )
            self._add_node(info)

        # Walk children for nested types (struct/union/enum inside struct)
        for child in node.children:
            if child.type in ("field_identifier",) and had_name and _node_text(child) == name:
                continue
            if child.type in ("primitive_type", "sized_type_specifier",
                              "type_qualifier", ","):
                continue
            if child.type in ("pointer_declarator", "array_declarator",
                              "function_declarator", "parenthesized_declarator"):
                # A pointer/array/function-pointer field's declarator names the
                # field itself (`char *name;`, `int arr[4];`). Do not walk that
                # subtree, otherwise the field_identifier leaf is visited as a
                # read reference from the struct to its own field.
                if had_name and _extract_declarator_name(child) == name:
                    continue
            self._walk(child)

    # ------------------------------------------------------------------
    # Type specifiers (struct/union/enum)
    # ------------------------------------------------------------------

    def _visit_type_specifier(self, node: Any) -> None:
        name = _extract_type_name(node)
        nt = node.type if hasattr(node, "type") else ""
        node_type = _CST_TYPE_TO_NODE_TYPE.get(nt, "type")

        body = node.child_by_field_name("body")
        has_body = body is not None
        if not has_body:
            has_field_list = any(
                c.type in ("field_declaration_list", "enumerator_list")
                for c in node.children
            )
        else:
            has_field_list = False

        is_definition = has_body or has_field_list

        # Enum/struct/union definitions create their own node (below);
        # enumerators get enum_member nodes via _visit_enumerator, so a use of
        # `RED` resolves to `mod.Color.RED` and keeps the enum alive. A bare
        # reference (`struct Point *p;`, `enum Color c;`) only emits a read
        # edge — it does not create a new node.
        if not is_definition:
            # Type reference — emit a read edge, don't create a new node.
            # Skip self-references: `struct Node { struct Node *next; };` —
            # a field whose type is the enclosing type is not an external
            # use. The reference would otherwise resolve to the type itself
            # (dropped as a self-edge) and could cross-link same-named types
            # in other files.
            if name and name != self._innermost_scope_name():
                sq = self._current_qname()
                self.references.append(ReferenceInfo(
                    source_qname=sq,
                    target_name=name,
                    edge_type="read",
                    line=_node_line(node),
                ))
                self.name_usages.add(name)
            return

        if not name:
            # Anonymous struct/union/enum definition (e.g.
            # `typedef struct { int x; } Item;` or
            # `void f(void) { struct { int a; } s; }`). It is not a named
            # symbol, so do NOT create a node: a phantom node here would share
            # the enclosing scope's qualified name and, in graph.py's
            # fnodes_map (last-writer-wins), silently clobber the enclosing
            # function/typedef node id and report live code as dead. Still
            # recurse into the body so fields stay attached to the enclosing
            # type via the current type/scope context.
            if body:
                self._walk(body)
            else:
                name_node = node.child_by_field_name("name")
                for child in node.children:
                    if child == name_node:
                        continue
                    if child.type in ("field_declaration_list", "enumerator_list"):
                        self._walk(child)
                    elif child.type in ("attribute_declaration", "attribute_specifier"):
                        continue
                    else:
                        self._walk(child)
            return

        qualified = self._current_qname() + "." + name

        info = NodeInfo(
            file_id=0,
            name=name,
            qualified_name=qualified,
            node_type=node_type,
            line_start=_node_line(node),
            line_end=_node_end_line(node),
            col_offset=_node_col(node),
            parent_node_id=self._current_type_id,
        )
        nid = self._add_node(info)

        prev_type_id = self._current_type_id
        self._current_type_id = nid
        self._push_scope(name)

        if body:
            self._walk(body)
        else:
            name_node = node.child_by_field_name("name")
            for child in node.children:
                if child == name_node:
                    continue
                if child.type in ("field_declaration_list", "enumerator_list"):
                    self._walk(child)
                elif child.type in ("attribute_declaration", "attribute_specifier"):
                    continue
                else:
                    self._walk(child)

        self._pop_scope()
        self._current_type_id = prev_type_id

    # ------------------------------------------------------------------
    # Enumerators (enum constants)
    # ------------------------------------------------------------------

    def _visit_enumerator(self, node: Any) -> None:
        """Create an ``enum_member`` node for each enumerator.

        ``enum Color { RED, GREEN };`` yields ``mod.Color.RED`` /
        ``mod.Color.GREEN`` with the enum node as parent, so a use of ``RED``
        resolves to the member, promotes it (``enum_member`` is a read-promoted
        type) and, through parent promotion, keeps the enclosing enum alive.
        Mirrors the C# backend's enum-member model. The enumerator's value
        expression is walked (``RED = BASE`` uses ``BASE``); the name
        identifier itself is not — reading one's own declaration is not a use.
        """
        name_node = node.child_by_field_name("name")
        if name_node is None:
            for child in node.children:
                if child.type in ("identifier", "field_identifier"):
                    name_node = child
                    break
        if name_node is None:
            for child in node.children:
                self._walk(child)
            return
        name = _node_text(name_node)
        if not name:
            return

        qualified = self._current_qname() + "." + name
        info = NodeInfo(
            file_id=0,
            name=name,
            qualified_name=qualified,
            node_type="enum_member",
            line_start=_node_line(node),
            line_end=_node_end_line(node),
            col_offset=_node_col(node),
            parent_node_id=self._current_type_id,
        )
        self._add_node(info)

        for child in node.children:
            # NOTE: tree-sitter materializes fresh Node wrappers per
            # ``.children`` access, so compare with ``==`` (Node equality is
            # structural) rather than ``is``.
            if child == name_node:
                continue
            self._walk(child)

    # ------------------------------------------------------------------
    # Typedef
    # ------------------------------------------------------------------

    def _visit_typedef(self, node: Any) -> None:
        name = _extract_type_name(node)
        if not name:
            return

        qualified = self._current_qname() + "." + name

        info = NodeInfo(
            file_id=0,
            name=name,
            qualified_name=qualified,
            node_type="type",
            line_start=_node_line(node),
            line_end=_node_end_line(node),
            col_offset=_node_col(node),
            parent_node_id=self._current_type_id,
        )
        nid = self._add_node(info)

        prev_type_id = self._current_type_id
        self._current_type_id = nid
        self._push_scope(name)

        for child in node.children:
            if child.type == "type_identifier" and _node_text(child) == name:
                continue
            self._walk(child)

        self._pop_scope()
        self._current_type_id = prev_type_id

    # ------------------------------------------------------------------
    # Macro definitions
    # ------------------------------------------------------------------

    def _visit_macro(self, node: Any) -> None:
        name = _extract_macro_name(node)
        if not name:
            return

        qualified = self._current_qname() + "." + name

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
    # #include preprocessor
    # ------------------------------------------------------------------

    def _visit_include(self, node: Any) -> None:
        info = self.import_analyzer.analyze_include(node)
        if info is not None:
            self.imports.append(info)

    # ------------------------------------------------------------------
    # Call expressions
    # ------------------------------------------------------------------

    def _visit_call(self, node: Any) -> None:
        cname = _extract_call_name(node)
        if cname:
            sq = self._current_qname()
            self.references.append(ReferenceInfo(
                source_qname=sq,
                target_name=cname,
                edge_type="call",
                line=_node_line(node),
            ))
            self.name_usages.add(cname)

        for child in node.children:
            self._walk(child)

    # ------------------------------------------------------------------
    # Field expression (obj.field or obj->field)
    # ------------------------------------------------------------------

    def _visit_field_expression(self, node: Any) -> None:
        # Walk all children; field_identifier children emit read/write edges
        for child in node.children:
            self._walk(child)

    # ------------------------------------------------------------------
    # Identifier references
    # ------------------------------------------------------------------

    def _is_declaration_parent(self, parent: Any) -> bool:
        """Check if parent is a declaration context (name intro, not usage)."""
        if parent is None or not hasattr(parent, "type"):
            return False
        ptype = parent.type
        return ptype in (
            "function_definition", "function_declarator",
            "struct_specifier", "union_specifier", "enum_specifier",
            "type_definition", "preproc_def", "preproc_function_def",
            "preproc_include", "preproc_params",
        )

    def _visit_identifier(self, node: Any) -> None:
        parent = node.parent
        if parent is None or not hasattr(parent, "type"):
            return

        ptype = parent.type

        if self._is_declaration_parent(parent):
            return

        if ptype in ("init_declarator", "declaration", "field_declaration"):
            # Check if this identifier is the name being declared
            if ptype == "declaration":
                for child in parent.children:
                    if child.type == "init_declarator":
                        decl = child.child_by_field_name("declarator")
                        if decl and _node_contains(decl, node):
                            return
            if ptype == "init_declarator":
                declarator = parent.child_by_field_name("declarator")
                if declarator and _node_contains(declarator, node):
                    # This is the LHS — write edge already handled in
                    # _visit_top_level_declaration; still track as usage below
                    pass

        name = _node_text(node)
        if not name:
            return

        # A name referenced by a preproc conditional (`#ifndef GUARD_H` /
        # `#ifdef FEATURE`) reaches this point and emits a genuine module-level
        # `read <module> -> NAME` edge (line > 0). find_connected_components
        # promotes macros with such a genuine module-level use when their file
        # is live, so include-guard and feature macros are not reported dead.
        sq = self._current_qname()

        if _is_on_left_of_assignment(node):
            self.references.append(ReferenceInfo(
                source_qname=sq,
                target_name=name,
                edge_type="write",
                line=_node_line(node),
            ))
            self.name_usages.add(name)
        else:
            self.references.append(ReferenceInfo(
                source_qname=sq,
                target_name=name,
                edge_type="read",
                line=_node_line(node),
            ))
            self.name_usages.add(name)

    def _visit_field_identifier_ref(self, node: Any) -> None:
        parent = node.parent
        if parent is None or not hasattr(parent, "type"):
            return

        if self._is_declaration_parent(parent):
            return

        name = _node_text(node)
        if not name:
            return

        sq = self._current_qname()

        if _is_on_left_of_assignment(node):
            self.references.append(ReferenceInfo(
                source_qname=sq,
                target_name=name,
                edge_type="write",
                line=_node_line(node),
            ))
            self.name_usages.add(name)
        else:
            self.references.append(ReferenceInfo(
                source_qname=sq,
                target_name=name,
                edge_type="read",
                line=_node_line(node),
            ))
            self.name_usages.add(name)

    def _visit_type_identifier_ref(self, node: Any) -> None:
        """type_identifier references — emit read edges for type usage."""
        parent = node.parent
        if parent is None or not hasattr(parent, "type"):
            return

        if self._is_declaration_parent(parent):
            return

        # NOTE: type_identifier leaves whose parent is a declarator name the
        # type being declared (`typedef`/`init_declarator`), not a use.
        # field_declaration / parameter_declaration parents are real type
        # uses (`Item item;` as a struct field or parameter) and emit read
        # edges so the typedef is kept alive when the container/function is.
        if parent.type in ("init_declarator",):
            return

        name = _node_text(node)
        if not name:
            return

        # Skip self-references (`S *p;` inside `struct S` — the enclosing
        # type's own name is not an external use).
        if name == self._innermost_scope_name():
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
    # Finalise
    # ------------------------------------------------------------------

    def finalize(self) -> None:
        """Called after walking — resolves any cross-node analysis."""
        pass
