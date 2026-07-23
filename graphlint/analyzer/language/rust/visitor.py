# -*- coding: utf-8 -*-
"""Tree-sitter CST visitor — traverses the concrete syntax tree to extract
nodes (symbol definitions), structured references (edges), and imports."""

from __future__ import annotations

from typing import Any, List, Optional, Set, Tuple

from graphlint.analyzer._types import NodeInfo, ReferenceInfo
from graphlint.analyzer.language.rust.constants import (
    _CST_TYPE_TO_NODE_TYPE,
    _IMPL_NODE_TYPES,
)
from graphlint.analyzer.language.rust.imports import (
    RustImportAnalyzer,
    UseInfo,
)


def _node_text(node: Any) -> str:
    """Decode tree-sitter node text safely."""
    try:
        return node.text.decode("utf-8") if node.text else ""
    except (UnicodeDecodeError, AttributeError):
        return ""


def _node_line(node: Any) -> int:
    """Return 1-based line number for a node."""
    try:
        return (node.start_point[0] + 1) if node.start_point else 0
    except (AttributeError, IndexError, TypeError):
        return 0


def _node_end_line(node: Any) -> int:
    """Return 1-based end line number for a node."""
    try:
        return (node.end_point[0] + 1) if node.end_point else 0
    except (AttributeError, IndexError, TypeError):
        return 0


def _node_col(node: Any) -> int:
    """Return 0-based column offset."""
    try:
        return node.start_point[1] if node.start_point else 0
    except (AttributeError, IndexError, TypeError):
        return 0


def _scoped_name(node: Any) -> str:
    """Extract the dotted name from a scoped_identifier or identifier node."""
    if node.type == "scoped_identifier":
        parts = []
        for child in node.children:
            if child.type == "identifier":
                parts.append(_node_text(child))
        return "::".join(parts)
    if node.type == "identifier":
        return _node_text(node)
    return ""


def _call_name_from_expr(expr_node: Any) -> str:
    """Extract the callable name from an expression node (function or method call).

    Handles:
        - foo()              → "foo"
        - obj.method()       → "method" (field_expression → field part)
        - crate::foo::bar()  → "crate::foo::bar" (scoped_identifier)
        - Type::method()     → "Type::method"
    """
    if expr_node.type == "identifier":
        return _node_text(expr_node)
    if expr_node.type == "scoped_identifier":
        return _scoped_name(expr_node)
    if expr_node.type == "field_expression":
        value = expr_node.child_by_field_name("value")
        field = expr_node.child_by_field_name("field")
        if field:
            return _node_text(field)
        # obj.associated_fn() — return the method name
        return _node_text(field) if field else ""
    if expr_node.type == "generic_function":
        # Foo::<T>::bar() — get the base function
        func = expr_node.child_by_field_name("function")
        if func:
            return _call_name_from_expr(func)
    return ""


class RustVisitor:
    """Walks a tree-sitter CST and extracts:

    * :class:`NodeInfo` — structs, enums, traits, functions, methods,
      constants, type aliases, modules, fields, variables
    * :class:`ReferenceInfo` — calls, reads, writes, trait implementations,
      attribute/macro decorations
    * :class:`UseInfo` — ``use`` declarations (via :class:`RustImportAnalyzer`)
    """

    def __init__(
        self,
        crate_qualified: str,
        file_path: str,
        import_analyzer: RustImportAnalyzer,
    ) -> None:
        self.crate_qualified = crate_qualified
        self.file_path = file_path
        self.import_analyzer = import_analyzer

        self.nodes: List[NodeInfo] = []
        self.references: List[ReferenceInfo] = []
        self.name_usages: Set[str] = set()
        self.uses: List[UseInfo] = []

        self._context: List[str] = [crate_qualified] if crate_qualified else []
        self._current_struct_id: int = 0
        self._current_struct_qname: str = ""
        self._current_trait_qname: str = ""
        self._current_impl_qname: str = ""
        self._node_id: int = 1
        self._field_qnames: Set[str] = set()

    # ------------------------------------------------------------------
    # Scope helpers
    # ------------------------------------------------------------------

    def _current_qname(self) -> str:
        return "::".join(self._context) if self._context else ""

    def _push_scope(self, name: str) -> None:
        self._context.append(name)

    def _pop_scope(self) -> None:
        if self._context:
            self._context.pop()

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def visit(self, tree: Any) -> None:
        """Walk the entire CST, extracting nodes, references, and imports."""
        root = tree.root_node if hasattr(tree, "root_node") else tree
        try:
            self._walk(root)
        except Exception:
            import sys
            import traceback

            print(
                f"[graphlint] CST visit error in {self.file_path}:",
                file=sys.stderr,
            )
            traceback.print_exc(file=sys.stderr)

    # ------------------------------------------------------------------
    # Recursive walk
    # ------------------------------------------------------------------

    def _walk(self, node: Any) -> None:
        """Dispatch by node type, then recurse into children."""
        ntype = node.type if hasattr(node, "type") else ""

        if ntype in _CST_TYPE_TO_NODE_TYPE:
            self._visit_definition(node, ntype)
        elif ntype == "impl_item":
            self._visit_impl_item(node)
        elif ntype == "use_declaration":
            self._visit_use(node)
        elif ntype == "field_declaration":
            self._visit_field_declaration(node)
        elif ntype == "let_declaration":
            self._visit_let_declaration(node)
        elif ntype == "call_expression":
            self._visit_call(node)
        elif ntype == "macro_invocation":
            self._visit_macro_invocation(node)
        elif ntype == "assignment_expression":
            self._visit_assignment(node)
        elif ntype == "compound_assignment_expr":
            self._visit_compound_assignment(node)
        elif ntype == "field_expression":
            self._visit_field_expr(node)
        elif ntype == "attribute_item":
            self._visit_attribute(node)
        elif ntype == "inner_attribute_item":
            self._visit_inner_attribute(node)
        elif ntype == "identifier":
            self._visit_identifier(node)
        elif ntype == "scoped_identifier":
            self._visit_scoped_identifier(node)
        elif ntype == "mod_item":
            self._visit_mod_item(node)
        else:
            # Recurse into children for unhandled node types
            for child in node.children:
                self._walk(child)

    # ------------------------------------------------------------------
    # Definition visitors
    # ------------------------------------------------------------------

    def _visit_definition(self, node: Any, ntype: str) -> None:
        """Handle function_item, struct_item, enum_item, trait_item, etc."""
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        name = _node_text(name_node)
        if not name:
            return

        qualified = self._current_qname() + ("::" + name if self._current_qname() else name)
        node_type = _CST_TYPE_TO_NODE_TYPE.get(ntype, "function")
        is_method = self._current_struct_id != 0

        # Distinguish method from function when inside an impl block
        if is_method and node_type == "function":
            node_type_val = _IMPL_NODE_TYPES.get(ntype, node_type)
        else:
            node_type_val = node_type

        is_pub = self._check_visibility(node)
        doc = self._extract_doc(node)
        type_ann = self._extract_return_type(node)
        is_deprecated = self._check_deprecated(node, doc)
        attr_names = self._extract_attribute_names(node)

        # Detect async functions
        is_async = False
        for child in node.children:
            if child.type == "async" or child.type == "async_modifier":
                is_async = True
                break

        info = NodeInfo(
            file_id=0,
            name=name,
            qualified_name=qualified,
            node_type=node_type_val,
            line_start=_node_line(node),
            line_end=_node_end_line(node),
            col_offset=_node_col(node),
            parent_node_id=self._current_struct_id,
            is_deprecated=is_deprecated,
            deprecation_msg="",
            type_annotation=type_ann,
            is_async=is_async,
            decorators=attr_names,
            docstring=doc,
            is_entry=False,
        )

        nid = self._add_node(info)

        # Determine which scope to enter for child items
        prev_struct_id = self._current_struct_id
        prev_struct_qname = self._current_struct_qname

        if ntype in ("struct_item", "enum_item", "union_item", "trait_item"):
            self._current_struct_id = nid
            self._current_struct_qname = qualified
            if ntype == "trait_item":
                self._current_trait_qname = qualified

        self._push_scope(name)

        # Visit type parameters and where clauses for read edges
        type_params = node.child_by_field_name("type_parameters")
        if type_params:
            self._walk(type_params)
        where_clause = node.child_by_field_name("where_clause")
        if where_clause:
            self._walk(where_clause)

        # Visit children (body, fields, etc.)
        body_fields = node.child_by_field_name("body") or node.child_by_field_name(
            "field_declaration_list"
        ) or node.child_by_field_name("declaration_list")
        if body_fields:
            self._walk(body_fields)
        else:
            for child in node.children:
                if child.type in (
                    "parameters",
                    "return_type",
                    "block",
                    "declaration_list",
                    "field_declaration_list",
                    "ordered_field_declaration_list",
                    "enum_variant_list",
                ):
                    self._walk(child)

        self._pop_scope()
        self._current_struct_id = prev_struct_id
        self._current_struct_qname = prev_struct_qname
        if ntype == "trait_item":
            self._current_trait_qname = ""

    def _visit_impl_item(self, node: Any) -> None:
        """Handle ``impl Type { ... }`` and ``impl Trait for Type { ... }`` blocks."""
        impl_type_name = ""
        trait_name = ""
        saw_for = False

        for child in node.children:
            if child.type in ("identifier", "type_identifier"):
                txt = _node_text(child)
                if saw_for:
                    impl_type_name = txt
                elif trait_name:
                    pass
                else:
                    trait_name = txt
            elif child.type == "scoped_type_identifier":
                txt = _scoped_name(child)
                if saw_for:
                    impl_type_name = txt
                else:
                    trait_name = txt
            elif child.type == "for":
                saw_for = True
            elif child.type == "generic_type":
                # e.g., impl<T> Foo<T>
                type_node = child.child_by_field_name("type")
                if type_node:
                    txt = _node_text(type_node)
                    if not impl_type_name:
                        impl_type_name = txt

        if saw_for and trait_name:
            # trait impl: impl Trait for Type
            final_trait = trait_name
            final_type = impl_type_name or trait_name
            # Emit inherit edge: Type → Trait
            type_qname = self._resolve_type_qname(final_type)
            trait_qname = self._resolve_type_qname(final_trait)
            self.references.append(ReferenceInfo(
                source_qname=type_qname,
                target_name=trait_qname,
                edge_type="inherit",
                line=_node_line(node),
            ))
            target_qname = type_qname
            self._current_impl_qname = final_type
        else:
            # inherent impl
            final_type = impl_type_name
            if not final_type:
                # Try to get type name from type node
                type_node = node.child_by_field_name("type")
                if type_node:
                    final_type = _node_text(type_node)
            target_qname = self._resolve_type_qname(final_type) if final_type else ""
            self._current_impl_qname = final_type

        # Visit the body to extract methods
        body = node.child_by_field_name("body")
        if body:
            prev_struct_id = self._current_struct_id
            prev_struct_qname = self._current_struct_qname
            # Methods in this impl are children of the target type
            if target_qname:
                self._current_struct_qname = target_qname
            self._walk(body)
            self._current_struct_id = prev_struct_id
            self._current_struct_qname = prev_struct_qname
        self._current_impl_qname = ""

    def _visit_mod_item(self, node: Any) -> None:
        """Handle ``mod foo;`` or ``mod foo { ... }`` declarations."""
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        name = _node_text(name_node)
        if not name:
            return

        qualified = self._current_qname() + ("::" + name if self._current_qname() else name)
        is_pub = self._check_visibility(node)
        doc = self._extract_doc(node)
        attr_names = self._extract_attribute_names(node)

        self._add_node(NodeInfo(
            file_id=0,
            name=name,
            qualified_name=qualified,
            node_type="module",
            line_start=_node_line(node),
            line_end=_node_end_line(node),
            col_offset=_node_col(node),
            parent_node_id=0,
            decorators=attr_names,
            docstring=doc,
        ))

        # Walk inline module body
        body = node.child_by_field_name("body")
        if body:
            self._push_scope(name)
            self._walk(body)
            self._pop_scope()

    def _visit_field_declaration(self, node: Any) -> None:
        """Handle struct/enum field declarations."""
        if not self._current_struct_qname:
            return

        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        name = _node_text(name_node)
        if not name:
            return

        qualified = self._current_struct_qname + "::" + name

        type_ann = ""
        type_node = node.child_by_field_name("type")
        if type_node:
            type_ann = _node_text(type_node)

        is_pub = self._check_visibility(node)
        doc = self._extract_doc(node)
        attr_names = self._extract_attribute_names(node)

        self._add_node(NodeInfo(
            file_id=0,
            name=name,
            qualified_name=qualified,
            node_type="field",
            line_start=_node_line(node),
            line_end=_node_end_line(node),
            col_offset=_node_col(node),
            parent_node_id=self._current_struct_id,
            type_annotation=type_ann,
            decorators=attr_names,
            docstring=doc,
        ))

        # Read edge: type annotation references
        if type_node:
            type_name = _node_text(type_node)
            if type_name and type_name not in ("i8", "i16", "i32", "i64", "i128",
                                                 "u8", "u16", "u32", "u64", "u128",
                                                 "f32", "f64", "bool", "char", "str",
                                                 "usize", "isize", "Self"):
                self.references.append(ReferenceInfo(
                    source_qname=qualified,
                    target_name=type_name,
                    edge_type="read",
                    line=_node_line(node),
                ))

    def _visit_let_declaration(self, node: Any) -> None:
        """Handle ``let x: Type = value;`` — extract variable definition."""
        pattern = node.child_by_field_name("pattern")
        if not pattern:
            return

        var_names = self._extract_pattern_names(pattern)
        if not var_names:
            return

        sq = self._current_qname()
        type_ann = ""
        type_node = node.child_by_field_name("type")
        if type_node:
            type_ann = _node_text(type_node)

        for vname in var_names:
            qualified = sq + ("::" + vname if sq else vname)
            self._add_node(NodeInfo(
                file_id=0,
                name=vname,
                qualified_name=qualified,
                node_type="variable",
                line_start=_node_line(node),
                line_end=_node_end_line(node),
                col_offset=_node_col(node),
                parent_node_id=self._current_struct_id or 0,
                type_annotation=type_ann,
            ))
            # Write edge
            self.references.append(ReferenceInfo(
                source_qname=sq,
                target_name=vname,
                edge_type="write",
                line=_node_line(node),
            ))

        # Visit the value expression
        value = node.child_by_field_name("value")
        if value:
            self._walk(value)

    # ------------------------------------------------------------------
    # Expression / reference visitors
    # ------------------------------------------------------------------

    def _visit_call(self, node: Any) -> None:
        """Handle ``foo()`` — emit a call edge."""
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
                # Track simple name usage
                simple = cname.split("::")[-1]
                self.name_usages.add(simple)

        # Recurse into all children
        for child in node.children:
            self._walk(child)

    def _visit_macro_invocation(self, node: Any) -> None:
        """Handle ``println!()``, ``vec![]``, ``derive(...)`` — emit a call-like edge."""
        name_node = None
        for child in node.children:
            if child.type in ("identifier", "scoped_identifier"):
                name_node = child
                break

        if name_node:
            cname = _scoped_name(name_node) if name_node.type == "scoped_identifier" else _node_text(name_node)
            if cname:
                sq = self._current_qname()
                self.references.append(ReferenceInfo(
                    source_qname=sq,
                    target_name=cname + "!",
                    edge_type="call",
                    line=_node_line(node),
                ))
                self.name_usages.add(cname)

        # Recurse
        for child in node.children:
            self._walk(child)

    def _visit_assignment(self, node: Any) -> None:
        """Handle ``x = value`` — emit a write edge."""
        left = node.child_by_field_name("left")
        if left:
            sq = self._current_qname()
            self._emit_write_ref(left, sq, _node_line(node))

        # Visit all children
        for child in node.children:
            self._walk(child)

    def _visit_compound_assignment(self, node: Any) -> None:
        """Handle ``x += value`` — emit read + write edges."""
        left = node.child_by_field_name("left")
        if left:
            sq = self._current_qname()
            self._emit_write_ref(left, sq, _node_line(node))
            self._emit_read_ref(left, sq, _node_line(node))

        for child in node.children:
            self._walk(child)

    def _visit_field_expr(self, node: Any) -> None:
        """Handle ``obj.field`` — emit a read edge for the field."""
        value = node.child_by_field_name("value")
        field = node.child_by_field_name("field")
        if field:
            field_name = _node_text(field)
            sq = self._current_qname()
            if field_name:
                self.references.append(ReferenceInfo(
                    source_qname=sq,
                    target_name=field_name,
                    edge_type="read",
                    line=_node_line(node),
                ))
                self.name_usages.add(field_name)
                # If value is a scoped_identifier like Type, emit read edges for each segment
                if value and value.type == "scoped_identifier":
                    for child in value.children:
                        if child.type == "identifier":
                            seg = _node_text(child)
                            self.name_usages.add(seg)

        for child in node.children:
            self._walk(child)

    def _visit_identifier(self, node: Any) -> None:
        """Generic identifier in read context — emit a read edge."""
        name = _node_text(node)
        if not name or name == "_":
            return
        # Skip Rust keywords and primitives
        if name in ("self", "Self", "mut", "ref", "crate", "super",
                     "i8", "i16", "i32", "i64", "i128",
                     "u8", "u16", "u32", "u64", "u128",
                     "f32", "f64", "bool", "char", "str",
                     "usize", "isize", "true", "false",
                     "fn", "let", "pub", "use", "mod", "impl",
                     "struct", "enum", "trait", "type", "const", "static",
                     "where", "for", "in", "if", "else", "match",
                     "while", "loop", "return", "break", "continue",
                     "async", "await", "move", "unsafe", "extern",
                     "as", "dyn", "box", "macro"):
            return
        self.name_usages.add(name)
        sq = self._current_qname()
        self.references.append(ReferenceInfo(
            source_qname=sq,
            target_name=name,
            edge_type="read",
            line=_node_line(node),
        ))

    def _visit_scoped_identifier(self, node: Any) -> None:
        """Handle ``path::to::Item`` — emit read edges for each segment."""
        name = _scoped_name(node)
        if name:
            sq = self._current_qname()
            self.references.append(ReferenceInfo(
                source_qname=sq,
                target_name=name,
                edge_type="read",
                line=_node_line(node),
            ))
        # Track simple segments
        for child in node.children:
            if child.type == "identifier":
                self.name_usages.add(_node_text(child))

    # ------------------------------------------------------------------
    # Attribute visitors
    # ------------------------------------------------------------------

    def _visit_attribute(self, node: Any) -> None:
        """Handle outer ``#[...]`` attributes — already handled per-item via
        ``_extract_attribute_names``.  Just walk children."""
        for child in node.children:
            self._walk(child)

    def _visit_inner_attribute(self, node: Any) -> None:
        """Handle ``#![...]`` crate-level attributes — walk children only."""
        for child in node.children:
            self._walk(child)

    # ------------------------------------------------------------------
    # Use declarations
    # ------------------------------------------------------------------

    def _visit_use(self, node: Any) -> None:
        """Handle ``use ...`` declarations."""
        use_info = self.import_analyzer.analyze_use(node, self.file_path)
        if use_info:
            self.uses.append(use_info)
            for n in use_info.imported_names:
                if n != "*":
                    self.name_usages.add(n)
                    if n in use_info.alias_map:
                        self.name_usages.add(use_info.alias_map[n])

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

    def _check_visibility(self, node: Any) -> bool:
        """Check if a definition has a ``pub`` visibility modifier."""
        vis = node.child_by_field_name("visibility_modifier")
        if vis:
            return True
        for child in node.children:
            if child.type == "visibility_modifier":
                return True
        return False

    def _resolve_type_qname(self, name: str) -> str:
        """Attempt to resolve a type name to a fully-qualified name."""
        if not name:
            return ""
        if "::" in name:
            return name
        prefix = self._current_qname()
        if prefix:
            return prefix + "::" + name
        return name

    def _extract_pattern_names(self, node: Any) -> list[str]:
        """Extract variable names from a pattern node."""
        names: list[str] = []
        if node.type == "identifier":
            n = _node_text(node)
            if n and n != "_" and n != "self":
                names.append(n)
        elif node.type == "mut_pattern":
            child = node.child_by_field_name("pattern") or (
                node.children[1] if len(node.children) > 1 else None
            )
            if child:
                names.extend(self._extract_pattern_names(child))
        elif node.type == "tuple_pattern":
            for child in node.children:
                names.extend(self._extract_pattern_names(child))
        elif node.type == "tuple_struct_pattern":
            for child in node.children:
                names.extend(self._extract_pattern_names(child))
        elif node.type == "struct_pattern":
            for child in node.children:
                # field_pattern: name or name: pattern
                if child.type == "field_pattern":
                    pat = child.child_by_field_name("pattern")
                    if pat:
                        names.extend(self._extract_pattern_names(pat))
                    else:
                        name_node = child.child_by_field_name("name")
                        if name_node:
                            n = _node_text(name_node)
                            if n and n != "_":
                                names.append(n)
        return names

    def _emit_write_ref(self, target: Any, sq: str, line: int) -> None:
        """Emit write references for an assignment target."""
        if target.type == "identifier":
            name = _node_text(target)
            if name and name != "_" and name != "self":
                self.references.append(ReferenceInfo(
                    source_qname=sq,
                    target_name=name,
                    edge_type="write",
                    line=line,
                ))
                self.name_usages.add(name)
        elif target.type == "field_expression":
            field = target.child_by_field_name("field")
            if field:
                name = _node_text(field)
                if name:
                    self.references.append(ReferenceInfo(
                        source_qname=sq,
                        target_name=name,
                        edge_type="write",
                        line=line,
                    ))
                    self.name_usages.add(name)
        elif target.type == "index_expression":
            pass  # arr[i] = val — no name to extract
        elif target.type in ("tuple_pattern", "tuple_struct_pattern"):
            for child in target.children:
                self._emit_write_ref(child, sq, line)
        elif target.type == "scoped_identifier":
            name = _scoped_name(target)
            if name:
                self.references.append(ReferenceInfo(
                    source_qname=sq,
                    target_name=name,
                    edge_type="write",
                    line=line,
                ))

    def _emit_read_ref(self, target: Any, sq: str, line: int) -> None:
        """Emit read references for an expression."""
        if target.type == "identifier":
            name = _node_text(target)
            if name and name != "_" and name != "self":
                self.references.append(ReferenceInfo(
                    source_qname=sq,
                    target_name=name,
                    edge_type="read",
                    line=line,
                ))
                self.name_usages.add(name)
        elif target.type == "field_expression":
            field = target.child_by_field_name("field")
            if field:
                name = _node_text(field)
                if name:
                    self.references.append(ReferenceInfo(
                        source_qname=sq,
                        target_name=name,
                        edge_type="read",
                        line=line,
                    ))
                    self.name_usages.add(name)

    @staticmethod
    def _extract_doc(node: Any) -> str:
        """Extract doc-comment text from preceding attribute items."""
        docs: list[str] = []
        parent = node.parent
        if parent:
            for child in parent.children:
                if child == node:
                    break
                if child.type in ("doc_comment", "line_comment", "block_comment"):
                    txt = _node_text(child).strip()
                    if child.type == "doc_comment":
                        txt = txt.lstrip("/! ").lstrip("///").strip()
                    docs.append(txt)
        result = "\n".join(docs)
        if len(result) > 500:
            result = result[:497] + "..."
        return result

    @staticmethod
    def _check_deprecated(node: Any, doc: str) -> bool:
        """Check if a definition is marked as deprecated."""
        combined = doc.lower()
        if "deprecated" in combined:
            return True
        for child in node.children:
            if child.type == "attribute_item":
                txt = _node_text(child).lower()
                if "deprecated" in txt:
                    return True
        return False

    def _extract_attribute_names(self, node: Any) -> list[str]:
        """Extract ``#[...]`` attribute names immediately preceding *node*.

        Stops at the first non-attribute sibling to avoid leakage
        between adjacent items.  Preserves scoped paths (``#[tokio::main]``
        → ``"tokio::main"``).
        """
        names: list[str] = []
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
                    if child.type == "attribute_item":
                        txt = _node_text(child)
                        if txt.startswith("#[") and txt.endswith("]"):
                            inner = txt[2:-1].strip()
                            attr_name = inner.split("(")[0].strip()
                            if attr_name:
                                names.insert(0, attr_name)
                    else:
                        break  # non-attribute sibling — stop
        return names

    @staticmethod
    def _extract_return_type(node: Any) -> str:
        """Extract return type annotation for a function."""
        ret = node.child_by_field_name("return_type")
        if ret:
            return _node_text(ret)
        return ""
