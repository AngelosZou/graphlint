# -*- coding: utf-8 -*-
"""GDScript CST visitor.

Turns a tree-sitter GDScript tree into graphlint graph material:

* one root ``script`` node per file whose qualified name is the ``res://``
  resource path (the file's identity in Godot),
* an alias ``class`` node for ``class_name X`` (qualified name
  ``<res path>.X``) which becomes the owner of the file's members, so that a
  cross-file type reference ``X`` or ``X.member`` resolves through the core's
  suffix index,
* member nodes (functions, signals, constants, enums, enum members, variables,
  fields, inner classes),
* references: ``call`` for direct calls, ``read`` for value/type/resource
  uses, ``write`` for member assignments and ``set("prop")``, ``inherit`` for
  ``extends``.

Liveness model (why the edges look the way they do)
---------------------------------------------------
``graphlint/analyzer/_graph_algo.py`` builds components from edges that avoid
node 0 and keeps a node alive only if something reaches it.  Godot has no
"public API by name" convention, so the adapter decides explicitly what a
resource keeps alive:

* data declarations (signal / constant / enum / enum member / ``class_name``
  alias) are an editor- and scene-facing surface: they get a ``read`` edge
  from their owner, so they are never reported as dead code;
* ``@export`` variables are written by the editor: also kept alive;
* plain ``var``/``@onready var`` and functions are *not* kept alive by default,
  so an uncalled method or an unread variable is a real finding;
* ``sender.signal.connect(handler)`` names both ends — the signal comes from the
  receiver chain, the handler from the callable argument (bare identifier,
  ``self.method``, ``method.bind(...)``, ``Callable(self, "method")``) — so an
  ordinary signal connection neither hides the handler nor marks the file
  unprovable;
* a *computed* name handed to ``get``/``set``/``call``/``emit_signal``
  (``dict.get(key, default)``, ``obj.call(name)``) can only reach one *kind* of
  member, so exactly that kind is kept alive — data members for a property name,
  functions for a method name, signals for a signal name — and the file stays
  provable, which keeps method-level dead code usable in scripts that merely
  read a dictionary by a variable key;
* a *literal* dispatch name that is not a member of this file
  (``call("other_script_method")``, ``emit_signal("died")``,
  ``dict.get("key")``) is not a property of this file: the name is handed to the
  project-wide dispatch pass, which keeps every same-named member anywhere
  alive, and the file stays provable;
* a file that contains a construct whose *target is a whole other script* — a
  computed ``load``/``get_node`` path, ``Expression``, ``str_to_var`` — gets
  every member kept alive instead: the adapter never claims dead code it cannot
  prove (``godot.assume_dynamic_keeps_file_alive``, default on).
"""

from __future__ import annotations

from typing import Any, Optional

from graphlint.analyzer._types import NodeInfo, ReferenceInfo

from .constants import (
    NODE_CLASS,
    NODE_CONSTANT,
    NODE_ENUM,
    NODE_ENUM_MEMBER,
    NODE_FIELD,
    NODE_FUNCTION,
    NODE_SIGNAL,
    NODE_VARIABLE,
)
from .imports import GodotImportInfo, config_section, is_res_path, normalize_res_path

#: Calls whose first string argument is a ``res://`` resource path.
_LOAD_CALLS: frozenset[str] = frozenset({"preload", "load"})

#: ``call``-family: the first string argument names a method.
_METHOD_DISPATCH_CALLS: frozenset[str] = frozenset(
    {"call", "callv", "call_deferred", "rpc", "rpc_id"}
)

#: ``get``-family: the first string argument names a property, read.
_PROPERTY_READ_CALLS: frozenset[str] = frozenset({"get", "get_deferred"})

#: ``set``-family: the first string argument names a property, written.
_PROPERTY_WRITE_CALLS: frozenset[str] = frozenset({"set", "set_deferred"})

#: Calls that take a NodePath; a computed path makes node access unprovable.
_NODE_ACCESS_CALLS: frozenset[str] = frozenset(
    {
        "get_node",
        "get_node_or_null",
        "find_child",
        "find_children",
        "find_parent",
    }
)

#: Calls that make the whole file unprovable.
_DYNAMIC_CALLS: frozenset[str] = frozenset({"str_to_var", "funcref", "instance_from_id"})

#: ``method.bind(args)``-family wrappers: the underlying callable is the
#: identifier the wrapper is called on (``show_scene.bind(x)`` → ``show_scene``).
_CALLABLE_BINDING_CALLS: frozenset[str] = frozenset(
    {"bind", "bindv", "call", "call_deferred"}
)

#: Node kinds a *computed* property name can reach (``get``/``set``).
_DATA_MEMBER_KINDS: frozenset[str] = frozenset({NODE_VARIABLE, NODE_FIELD})

#: Node kinds a *computed* method name can reach (``call``/``rpc``/``Callable``).
_METHOD_MEMBER_KINDS: frozenset[str] = frozenset({NODE_FUNCTION})

#: Node kinds a *computed* signal name can reach (``emit_signal``).
_SIGNAL_MEMBER_KINDS: frozenset[str] = frozenset({NODE_SIGNAL})

_EXPORT_PREFIX = "@export"

#: Annotation names that mark a variable as an editor-facing field.
_FIELD_ANNOTATIONS: frozenset[str] = frozenset(
    {"@export", "@onready"} | {_EXPORT_PREFIX}
)

#: Annotations that belong to the *file* rather than to a declaration.  Every
#: other annotation (``@rpc``, ``@export``, ``@onready``, ``@warning_ignore`` …)
#: annotates the declaration that follows it.
_FILE_ANNOTATIONS: frozenset[str] = frozenset({"@tool", "@icon"})


class GdVisitor:
    """Collect nodes and references from one GDScript file."""

    def __init__(
        self,
        module_qname: str,
        file_path: str,
        source: bytes,
        config: Optional[dict[str, Any]] = None,
    ) -> None:
        self.module_qname = module_qname
        self.file_path = file_path
        self.source = source
        self.cfg = config_section(config)

        self.nodes: list[NodeInfo] = []
        self.references: list[ReferenceInfo] = []
        self.imports: list[GodotImportInfo] = []
        self.name_usages: set[str] = set()
        self.warnings: list[Any] = []

        self._node_id = 1
        self.root_id = 0
        self.class_name = ""
        self.class_id = 0
        self.base_target = ""
        #: the node that owns the members currently being declared
        self.owner_qname = module_qname
        self.owner_id = 0
        #: simple member name -> qualified name, for exact reference targets
        self.member_names: set[str] = set()
        self.member_qnames: dict[str, str] = {}
        #: member name -> declared type text (``@onready var player: Player``),
        #: used to turn ``player.take_damage`` into ``Player.take_damage``
        self.member_types: dict[str, str] = {}
        #: names declared with ``var`` (an instance value): a ``recv.member``
        #: whose receiver is one of these and whose type is unknown stays
        #: unresolved instead of guessing a cross-file symbol
        self._value_names: set[str] = set()
        #: function-scoped local name -> declared or inferred type text
        self._local_types: dict[str, str] = {}
        self._local_names: set[str] = set()
        #: every literal name used in string-keyed dispatch anywhere in the
        #: file — published so a project-wide pass can keep same-named methods
        #: alive (``call("add_score")`` in one script reaches another script's
        #: method, which no single-file analysis can see)
        self.dispatch_names: set[str] = set()
        #: owner->member keep-alive edges, emitted in :meth:`finish`
        self._pending_liveness: list[tuple[str, str, int]] = []
        #: unresolved string-keyed dispatch: (name, line, scope, kind)
        self._string_dispatch: list[tuple[str, int, str, str]] = []
        #: computed-name dispatch: (member kinds it can reach, line).  Applied
        #: in :meth:`finish`, once every declaration of the file is known.
        self._keep_kinds: list[tuple[frozenset[str], int]] = []
        self.dynamic = False
        #: lines carrying an unprovable dynamic construct (for the report)
        self.dynamic_lines: list[int] = []
        self._file_level_annotations: list[str] = []

    # ------------------------------------------------------------------
    # entry point
    # ------------------------------------------------------------------

    def visit(self, tree: Any) -> None:
        """Walk *tree* (a tree-sitter GDScript tree)."""
        root = tree.root_node
        line_count = root.end_point[0] + 1
        self._collect_member_names(root)
        self.owner_id = self._add_node(
            name=_basename(self.file_path),
            qname=self.module_qname,
            node_type=_script_node_type(self.file_path),
            line_start=1,
            line_end=line_count,
            parent_id=0,
            decorators=self._prologue_annotations(root),
        )
        self.root_id = self.owner_id
        self._walk_declarations(root)
        self.finish()

    # ------------------------------------------------------------------
    # declarations
    # ------------------------------------------------------------------

    def _walk_declarations(self, container: Any) -> None:
        """Walk a ``source``/``class_body`` container, creating member nodes."""
        pending: list[str] = []
        for child in container.named_children:
            node_type = child.type
            if node_type in ("annotation", "annotations"):
                pending.extend(self._annotation_names(child))
                continue
            if node_type == "comment":
                continue
            if node_type == "class_name_statement":
                self._handle_class_name(child, pending)
                pending = []
                continue
            if node_type == "extends_statement":
                self._handle_extends(child)
                pending = []
                continue
            if node_type in ("function_definition", "constructor_definition"):
                self._handle_function(child, pending)
            elif node_type == "signal_statement":
                self._handle_signal(child, pending)
            elif node_type == "const_statement":
                self._handle_const(child, pending)
            elif node_type == "variable_statement":
                self._handle_variable(child, pending)
            elif node_type == "enum_definition":
                self._handle_enum(child, pending)
            elif node_type == "class_definition":
                self._handle_class(child, pending)
            else:
                self._walk_statement(child, self.owner_qname)
            pending = []

    def _handle_class_name(self, node: Any, annotations: list[str]) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        name = self._text(name_node)
        line = node.start_point[0] + 1
        qname = f"{self.module_qname}.{name}"
        class_id = self._add_node(
            name=name,
            qname=qname,
            node_type=NODE_CLASS,
            line_start=line,
            line_end=node.end_point[0] + 1,
            parent_id=self.root_id,
            decorators=annotations + self._file_level_annotations,
        )
        self.class_name = name
        self.class_id = class_id
        # Members are owned by the class alias when there is one: a reference
        # to the type then reaches the members through the same qualified name
        # a reader would write (`Player.take_damage`).
        self.owner_qname = qname
        self.owner_id = class_id
        self.member_names.add(name)
        self.member_qnames[name] = qname
        # Keep the alias and the resource both alive: an entry may reach either
        # (a scene attaches the *resource*, a type reference names the *class*).
        self._add_ref(self.module_qname, qname, "read", line)
        self._add_ref(qname, self.module_qname, "read", line)
        # ``class_name X extends "res://base.gd"`` carries a nested extends.
        for child in node.named_children:
            if child.type == "extends_statement":
                self._handle_extends(child)
                break

    def _handle_extends(self, node: Any) -> None:
        line = node.start_point[0] + 1
        children = node.named_children
        if not children:
            return
        target = children[0]
        if target.type == "string":
            raw = self._string_value(target)
            if raw and is_res_path(raw):
                path = normalize_res_path(raw)
                self.imports.append(
                    GodotImportInfo(path=path, line=line, kind="extends")
                )
                self._add_ref(self.module_qname, path, "inherit", line)
                self._add_ref(self.module_qname, path, "read", line)
                if not self.base_target:
                    self.base_target = path
            return
        name = self._text(target)
        if not name:
            return
        self.name_usages.add(name)
        self._add_ref(self.module_qname, name, "inherit", line)
        self._add_ref(self.module_qname, name, "read", line)
        if not self.base_target:
            self.base_target = name

    def _handle_function(self, node: Any, annotations: list[str]) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is not None:
            name = self._text(name_node)
        elif node.type == "constructor_definition":
            name = "_init"
        else:
            name = "<anonymous>"
        line = node.start_point[0] + 1
        qname = f"{self.owner_qname}.{name}"
        self._add_node(
            name=name,
            qname=qname,
            node_type=NODE_FUNCTION,
            line_start=line,
            line_end=node.end_point[0] + 1,
            parent_id=self.owner_id,
            decorators=annotations,
            type_annotation=self._type_text(node.child_by_field_name("return_type")),
        )
        self.member_names.add(name)
        self.member_qnames[name] = qname

        saved_locals = (self._local_types, self._local_names)
        self._local_types, self._local_names = {}, set()
        params = node.child_by_field_name("parameters")
        if params is not None:
            for param in params.named_children:
                self._walk_type(param.child_by_field_name("type"), qname)
                # a typed parameter is a local binding: ``func hit(target: Player)``
                # followed by ``target.take_damage(1)`` must reach ``Player.take_damage``
                pname = self._parameter_name(param)
                if not pname:
                    continue
                self._local_names.add(pname)
                self._local_types[pname] = self._type_text(
                    param.child_by_field_name("type")
                )
        body = node.child_by_field_name("body")
        if body is not None:
            self._walk_body(body, qname)
        self._local_types, self._local_names = saved_locals
        if not self.cfg.get("method_dead_code", False):
            self._keep_alive(self.owner_qname, qname, line)

    def _handle_signal(self, node: Any, annotations: list[str]) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        name = self._text(name_node)
        line = node.start_point[0] + 1
        qname = f"{self.owner_qname}.{name}"
        self._add_node(
            name=name,
            qname=qname,
            node_type=NODE_SIGNAL,
            line_start=line,
            line_end=node.end_point[0] + 1,
            parent_id=self.owner_id,
            decorators=annotations,
        )
        self.member_names.add(name)
        self.member_qnames[name] = qname
        if not self.cfg.get("signal_dead_code", False):
            self._keep_alive(self.owner_qname, qname, line)

    def _handle_const(self, node: Any, annotations: list[str]) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        annotations = list(annotations) + self._node_annotations(node)
        name = self._text(name_node)
        line = node.start_point[0] + 1
        qname = f"{self.owner_qname}.{name}"
        type_text = self._type_text(node.child_by_field_name("type"))
        self._add_node(
            name=name,
            qname=qname,
            node_type=NODE_CONSTANT,
            line_start=line,
            line_end=node.end_point[0] + 1,
            parent_id=self.owner_id,
            decorators=annotations,
            type_annotation=type_text,
        )
        self.member_names.add(name)
        self.member_qnames[name] = qname
        self.member_types[name] = type_text
        value = node.child_by_field_name("value")
        if not self._handle_literal_load(value, name, line):
            self._walk_statement(value, self.owner_qname)
        self._walk_type(node.child_by_field_name("type"), self.owner_qname)
        if not self.cfg.get("constant_dead_code", False):
            self._keep_alive(self.owner_qname, qname, line)

    def _handle_variable(self, node: Any, annotations: list[str]) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        # ``@export var x`` nests its annotation inside the statement, while
        # ``@rpc func f()`` uses a preceding sibling — accept both.
        annotations = list(annotations) + self._node_annotations(node)
        name = self._text(name_node)
        line = node.start_point[0] + 1
        qname = f"{self.owner_qname}.{name}"
        is_field = any(
            a in _FIELD_ANNOTATIONS or a.startswith(_EXPORT_PREFIX + "_")
            for a in annotations
        )
        node_type = NODE_FIELD if is_field else NODE_VARIABLE
        type_text = self._type_text(node.child_by_field_name("type"))
        self._add_node(
            name=name,
            qname=qname,
            node_type=node_type,
            line_start=line,
            line_end=node.end_point[0] + 1,
            parent_id=self.owner_id,
            decorators=annotations,
            type_annotation=type_text,
        )
        self.member_names.add(name)
        self.member_qnames[name] = qname
        self.member_types[name] = type_text
        self._value_names.add(name)
        value = node.child_by_field_name("value")
        if not self._handle_literal_load(value, name, line):
            self._walk_statement(value, self.owner_qname)
        self._walk_type(node.child_by_field_name("type"), self.owner_qname)
        if is_field:
            # ``@export`` variables are written by the editor and may be read
            # by another scene: never report them as unused.
            self._keep_alive(self.owner_qname, qname, line)

    def _handle_enum(self, node: Any, annotations: list[str]) -> None:
        name_node = node.child_by_field_name("name")
        name = self._text(name_node) if name_node is not None else "<anonymous>"
        line = node.start_point[0] + 1
        qname = f"{self.owner_qname}.{name}"
        enum_id = self._add_node(
            name=name,
            qname=qname,
            node_type=NODE_ENUM,
            line_start=line,
            line_end=node.end_point[0] + 1,
            parent_id=self.owner_id,
            decorators=annotations,
        )
        self.member_names.add(name)
        self.member_qnames[name] = qname
        keep = not self.cfg.get("constant_dead_code", False)
        if keep:
            self._keep_alive(self.owner_qname, qname, line)
        body = node.child_by_field_name("body")
        if body is None:
            for child in node.named_children:
                if child.type == "enumerator_list":
                    body = child
                    break
        if body is None:
            return
        for enumerator in body.named_children:
            if enumerator.type != "enumerator":
                continue
            member_name_node = enumerator.child_by_field_name("left")
            if member_name_node is None:
                member_name_node = (
                    enumerator.named_children[0] if enumerator.named_children else None
                )
            if member_name_node is None:
                continue
            member_name = self._text(member_name_node)
            member_line = enumerator.start_point[0] + 1
            member_qname = f"{qname}.{member_name}"
            self._add_node(
                name=member_name,
                qname=member_qname,
                node_type=NODE_ENUM_MEMBER,
                line_start=member_line,
                line_end=enumerator.end_point[0] + 1,
                parent_id=enum_id,
            )
            self.member_names.add(member_name)
            self.member_qnames.setdefault(member_name, member_qname)
            if keep:
                self._keep_alive(self.owner_qname, member_qname, member_line)

    def _handle_class(self, node: Any, annotations: list[str]) -> None:
        name_node = node.child_by_field_name("name")
        name = self._text(name_node) if name_node is not None else "<anonymous>"
        line = node.start_point[0] + 1
        qname = f"{self.owner_qname}.{name}"
        class_id = self._add_node(
            name=name,
            qname=qname,
            node_type=NODE_CLASS,
            line_start=line,
            line_end=node.end_point[0] + 1,
            parent_id=self.owner_id,
            decorators=annotations,
        )
        self.member_names.add(name)
        self.member_qnames.setdefault(name, qname)

        body = None
        for child in node.named_children:
            if child.type == "class_body":
                body = child
                break
        saved = (self.owner_qname, self.owner_id, self.base_target)
        self.owner_qname, self.owner_id = qname, class_id
        self.base_target = ""
        if body is not None:
            for child in body.named_children:
                if child.type == "extends_statement":
                    base_line = child.start_point[0] + 1
                    base_children = child.named_children
                    if base_children:
                        base_node = base_children[0]
                        if base_node.type == "string":
                            raw = self._string_value(base_node)
                            if raw and is_res_path(raw):
                                path = normalize_res_path(raw)
                                self.imports.append(
                                    GodotImportInfo(
                                        path=path, line=base_line, kind="extends"
                                    )
                                )
                                self._add_ref(qname, path, "inherit", base_line)
                                self._add_ref(qname, path, "read", base_line)
                        else:
                            base_name = self._text(base_node)
                            if base_name:
                                self._add_ref(qname, base_name, "inherit", base_line)
                                self._add_ref(qname, base_name, "read", base_line)
                    break
            self._walk_declarations(body)
        self.owner_qname, self.owner_id, self.base_target = saved

    # ------------------------------------------------------------------
    # statements and expressions
    # ------------------------------------------------------------------

    def _walk_body(self, body: Any, scope: str) -> None:
        for child in body.named_children:
            self._walk_statement(child, scope)

    def _walk_statement(self, node: Any, scope: str) -> None:
        if node is None:
            return
        node_type = node.type
        if node_type in ("call", "attribute_call"):
            self._handle_call(node, scope)
        elif node_type == "attribute":
            self._handle_attribute(node, scope)
        elif node_type == "identifier":
            self._handle_identifier(node, scope)
        elif node_type == "assignment":
            self._handle_assignment(node, scope, augmented=False)
        elif node_type == "augmented_assignment":
            self._handle_assignment(node, scope, augmented=True)
        elif node_type == "variable_statement":
            # a local variable: no member node, but its initialiser and type
            # may still reference project symbols, and its declared/inferred
            # type lets ``local.member`` resolve to an exact symbol
            self._record_local(node)
            value = node.child_by_field_name("value")
            self._walk_statement(value, scope)
            self._walk_type(node.child_by_field_name("type"), scope)
        elif node_type in ("function_definition", "constructor_definition", "lambda"):
            body = node.child_by_field_name("body")
            if body is None:
                for child in node.named_children:
                    self._walk_statement(child, scope)
            else:
                self._walk_body(body, scope)
        elif node_type == "type":
            self._walk_type(node, scope)
        elif node_type in ("string", "comment"):
            return
        else:
            for child in node.named_children:
                self._walk_statement(child, scope)

    def _handle_call(self, node: Any, scope: str) -> None:
        children = node.named_children
        if not children:
            return
        callee = children[0]
        args = node.child_by_field_name("arguments")
        if args is None:
            for child in children:
                if child.type == "arguments":
                    args = child
                    break
        line = node.start_point[0] + 1
        if callee.type == "identifier":
            self._emit_call(scope, None, self._text(callee), args, line)
        elif callee.type == "attribute":
            self._handle_attribute(callee, scope, call_args=args)
        else:
            self._walk_statement(callee, scope)
            self._walk_arguments(args, scope)

    def _handle_attribute(
        self, node: Any, scope: str, call_args: Any = None
    ) -> None:
        children = node.named_children
        if not children:
            return
        receiver = children[0]
        line = node.start_point[0] + 1

        attribute_call = None
        for child in children[1:]:
            if child.type == "attribute_call":
                attribute_call = child
                break

        if attribute_call is not None:
            name_node = None
            args = call_args
            for child in attribute_call.named_children:
                if child.type == "arguments":
                    args = child
                elif name_node is None:
                    name_node = child
            name = self._text(name_node) if name_node is not None else ""
            # the identifier in front of the call: ``sender.signal.connect(…)``
            # names the signal here, not in the (type-unknown) receiver chain
            recv_link = ""
            for child in children:
                if child is attribute_call:
                    break
                if child.type == "identifier":
                    recv_link = self._text(child)
            self._emit_call(scope, receiver, name, args, line, recv_link=recv_link)
            return

        if call_args is not None:
            # ``f(...)`` where the callee is a complex attribute expression
            self._walk_statement(receiver, scope)
            self._walk_arguments(call_args, scope)
            return

        member_node = children[-1] if len(children) > 1 else None
        if receiver.type == "identifier":
            recv_text = self._text(receiver)
            self.name_usages.add(recv_text)
            if member_node is None:
                return
            member = self._text(member_node)
            if recv_text == "self":
                target = self.member_qnames.get(member)
                if target is not None:
                    self._add_ref(scope, target, "read", line)
                return
            # ``State.A`` / ``Player.CONST`` / ``Type.nested``: keep both the
            # container and the exact member alive.  A typed receiver is
            # rewritten to ``Type.member``; an untyped value stays unresolved
            # rather than guessing a suffix match the resolver fails open on.
            target = self._qualified_member(recv_text, member)
            if target is not None:
                self._add_ref(scope, target, "read", line)
            self._add_ref(scope, recv_text, "read", line)
        else:
            self._walk_statement(receiver, scope)

    def _emit_call(
        self,
        scope: str,
        receiver: Any,
        name: str,
        args: Any,
        line: int,
        recv_link: str = "",
    ) -> None:
        recv_text = self._text(receiver) if receiver is not None else ""
        if receiver is not None and receiver.type == "identifier":
            self.name_usages.add(recv_text)

        if not name:
            self._walk_arguments(args, scope)
            return

        bare = receiver is None or recv_text in ("self", "super")
        if name in _LOAD_CALLS and not recv_text:
            self._handle_load_call(scope, name, args, line)
        elif name in _DYNAMIC_CALLS:
            self._mark_dynamic(line)
        elif name == "Expression.parse" or (recv_text == "Expression" and name == "parse"):
            self._mark_dynamic(line)
        elif self._handle_dispatch_call(
            scope, recv_text, name, args, line, recv_link=recv_link
        ):
            pass
        elif receiver is None:
            self._add_ref(scope, name, "call", line)
        elif recv_text == "self":
            target = self.member_qnames.get(name)
            self._add_ref(scope, target if target is not None else name, "call", line)
        elif recv_text == "super":
            base = self.base_target
            self._add_ref(scope, f"{base}.{name}" if base else name, "call", line)
        elif receiver.type == "identifier":
            self._add_ref(scope, recv_text, "read", line)
            target = self._qualified_member(recv_text, name)
            if target is not None:
                self._add_ref(scope, target, "call", line)
        else:
            self._walk_statement(receiver, scope)

        self._walk_arguments(args, scope)

    def _handle_load_call(self, scope: str, name: str, args: Any, line: int) -> None:
        arg_nodes = self._arg_nodes(args)
        if not arg_nodes:
            return
        raw = self._string_value(arg_nodes[0])
        if raw is None:
            # ``load(some_path)`` — the dependency is not statically known.
            self._mark_dynamic(line)
            return
        if not is_res_path(raw):
            return
        path = normalize_res_path(raw)
        self.imports.append(
            GodotImportInfo(
                path=path, line=line, kind="preload" if name == "preload" else "load"
            )
        )
        self._add_ref(scope, path, "read", line)

    def _handle_literal_load(self, value: Any, name: str, line: int) -> bool:
        """Handle ``const X = preload("res://…")`` (named resource import)."""
        if value is None:
            return False
        call = value
        if call.type not in ("call", "attribute_call"):
            return False
        children = call.named_children
        if not children:
            return False
        callee = children[0]
        if callee.type == "identifier" and self._text(callee) == "preload":
            args = None
            for child in children[1:]:
                if child.type == "arguments":
                    args = child
                    break
            arg_nodes = self._arg_nodes(args)
            if arg_nodes:
                raw = self._string_value(arg_nodes[0])
                if raw and is_res_path(raw):
                    path = normalize_res_path(raw)
                    self.imports.append(
                        GodotImportInfo(
                            path=path, line=line, kind="preload", name=name
                        )
                    )
                    self._add_ref(self.owner_qname, path, "read", line)
                    return True
        return False

    def _handle_dispatch_call(
        self,
        scope: str,
        recv_text: str,
        name: str,
        args: Any,
        line: int,
        recv_link: str = "",
    ) -> bool:
        """String-keyed engine dispatch (``call``/``connect``/``emit_signal``…).

        Returns True when the call was recognised; a literal name is deferred
        to :meth:`finish` (it may reference a member declared later), anything
        computed marks the file unprovable.
        """
        arg_nodes = self._arg_nodes(args)

        def string_arg(index: int) -> Optional[str]:
            if index < len(arg_nodes):
                return self._string_value(arg_nodes[index])
            return None

        if name in ("connect", "connect_flags"):
            # Two shapes exist: the legacy ``obj.connect("signal", callable)``
            # (signal first) and the Godot 4 ``sender.signal.connect(callable)``
            # (signal in the receiver chain, handler first).
            signal_name = string_arg(0)
            handler_node = None
            if signal_name is not None:
                if len(arg_nodes) > 1:
                    handler_node = arg_nodes[1]
            else:
                signal_name = recv_link or None
                if arg_nodes:
                    handler_node = arg_nodes[0]
            if signal_name:
                self._string_dispatch.append((signal_name, line, scope, "signal"))
            handler_known = False
            if handler_node is not None:
                callable_name = self._callable_name(handler_node)
                if callable_name:
                    self._string_dispatch.append((callable_name, line, scope, "value"))
                    handler_known = True
                elif handler_node.type == "lambda":
                    # a closure is self-contained: nothing outside it is called
                    handler_known = True
            if not signal_name and not handler_known:
                # neither end of the connection is known: unprovable
                self._mark_dynamic(line)
            return True

        if name == "emit_signal":
            signal_name = string_arg(0)
            if signal_name:
                self._string_dispatch.append((signal_name, line, scope, "signal"))
            else:
                # a computed signal name can only reach a signal declaration
                self._keep_kinds.append((_SIGNAL_MEMBER_KINDS, line))
            return True

        if name in _METHOD_DISPATCH_CALLS:
            method_name = string_arg(0)
            if method_name:
                self._string_dispatch.append((method_name, line, scope, "method"))
            else:
                # a computed method name can only reach a function
                self._keep_kinds.append((_METHOD_MEMBER_KINDS, line))
            return True

        if name in _PROPERTY_READ_CALLS:
            prop = string_arg(0)
            if prop:
                self._string_dispatch.append((prop, line, scope, "value"))
            else:
                # a computed property name can only reach a variable/field
                self._keep_kinds.append((_DATA_MEMBER_KINDS, line))
            return True

        if name in _PROPERTY_WRITE_CALLS:
            prop = string_arg(0)
            if prop:
                self._string_dispatch.append((prop, line, scope, "write"))
            else:
                self._keep_kinds.append((_DATA_MEMBER_KINDS, line))
            return True

        if name in _NODE_ACCESS_CALLS:
            if string_arg(0) is None:
                # a computed NodePath: any node (and thus any attached script)
                # could be the target
                self._mark_dynamic(line)
            return True

        if name == "Callable":
            method_name = string_arg(1)
            if method_name:
                self._string_dispatch.append((method_name, line, scope, "value"))
            elif string_arg(0) is not None or len(arg_nodes) > 0:
                # ``Callable(obj, computed_name)``: the name is resolved against
                # ``obj``, so only a method can be reached
                self._keep_kinds.append((_METHOD_MEMBER_KINDS, line))
            return True

        return False

    def _handle_assignment(self, node: Any, scope: str, augmented: bool) -> None:
        children = node.named_children
        if len(children) < 2:
            for child in children:
                self._walk_statement(child, scope)
            return
        left = node.child_by_field_name("left") or children[0]
        right = node.child_by_field_name("right") or children[-1]
        line = node.start_point[0] + 1

        target: Optional[str] = None
        if left is not None and left.type == "identifier":
            name = self._text(left)
            self.name_usages.add(name)
            target = self.member_qnames.get(name)
        elif left is not None and left.type == "attribute":
            left_children = left.named_children
            if left_children and self._text(left_children[0]) == "self":
                member = self._text(left_children[-1])
                target = self.member_qnames.get(member)

        if target is not None:
            if augmented:
                # ``x += 1`` reads and writes
                self._add_ref(scope, target, "read", line)
            self._add_ref(scope, target, "write", line)
        elif left is not None and left is not right:
            self._walk_statement(left, scope)

        if right is not None and right is not left:
            self._walk_statement(right, scope)

    def _handle_identifier(self, node: Any, scope: str) -> None:
        name = self._text(node)
        if not name:
            return
        self.name_usages.add(name)
        target = self.member_qnames.get(name)
        if target is not None and target != scope:
            self._add_ref(scope, target, "read", node.start_point[0] + 1)

    def _walk_arguments(self, args: Any, scope: str) -> None:
        for arg in self._arg_nodes(args):
            if self._string_value(arg) is not None:
                continue
            self._walk_statement(arg, scope)

    def _walk_type(self, node: Any, scope: str) -> None:
        """Emit ``read`` references for a type annotation position."""
        if node is None:
            return
        if node.type == "identifier":
            name = self._text(node)
            if name:
                self.name_usages.add(name)
                self._add_ref(scope, name, "read", node.start_point[0] + 1)
            return
        for child in node.named_children:
            self._walk_type(child, scope)

    # ------------------------------------------------------------------
    # finish: deferred string dispatch + liveness edges
    # ------------------------------------------------------------------

    def finish(self) -> None:
        # every literal name used in string-keyed dispatch, resolved here or
        # not: a project-wide pass keeps same-named methods alive, because
        # ``call("add_score")`` in one script can reach another script's method
        self.dispatch_names = {
            name for name, _line, _scope, _kind in self._string_dispatch
        }
        for name, line, scope, kind in self._string_dispatch:
            target = self.member_qnames.get(name)
            if target is None:
                # The literal is not a member of this file: it names a member of
                # another file (or an engine signal).  That member is kept alive
                # by the project-wide dispatch pass, and the fact that a *remote*
                # name is unresolvable says nothing about this file's members —
                # in particular ``dict.get("key")`` is a Dictionary lookup, not a
                # property dispatch.
                continue
            edge_type = {
                "method": "call",
                "value": "read",
                "signal": "read",
                "write": "write",
            }.get(kind, "read")
            self._add_ref(scope, target, edge_type, line)

        for kinds, line in self._keep_kinds:
            self._keep_member_kinds_alive(kinds, line)

        if self.dynamic and self.cfg.get("assume_dynamic_keeps_file_alive", True):
            # An unprovable dynamic construct may reach any member: keep the
            # whole file alive rather than claim dead code we cannot prove.
            for target in sorted(set(self.member_qnames.values())):
                if target != self.owner_qname:
                    self._pending_liveness.append((self.owner_qname, target, 1))

        for owner, target, line in self._pending_liveness:
            self._add_ref(owner, target, "read", line)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _keep_alive(self, owner: str, target: str, line: int) -> None:
        self._pending_liveness.append((owner, target, line))

    def _keep_member_kinds_alive(
        self, node_types: frozenset[str], line: int
    ) -> None:
        """Keep every member of the given kinds alive.

        A *computed* name handed to ``get``/``set``/``call``/``emit_signal``
        cannot be matched to a declaration statically, but it can only ever
        reach members of one kind: a dynamic property name reaches a
        variable/field, a dynamic method name reaches a function, a dynamic
        signal name reaches a signal.  Keeping exactly that kind alive leaves
        the file provable — unlike the file-wide gate — while still refusing to
        call the members dead, which is the conservative direction.
        """
        for node in self.nodes:
            if node.node_type in node_types and node.qualified_name != self.owner_qname:
                self._pending_liveness.append(
                    (self.owner_qname, node.qualified_name, line)
                )

    def _parameter_name(self, param: Any) -> str:
        """Name of a parameter node.

        The grammar puts the type in a ``type`` field but leaves the name as a
        bare ``identifier`` child (``typed_parameter``, ``default_parameter``,
        ``typed_default_parameter``), so it must be found positionally.
        """
        name_node = param.child_by_field_name("name")
        if name_node is None:
            # an untyped parameter is a bare ``identifier`` node
            if param.type == "identifier":
                name_node = param
            else:
                for child in param.named_children:
                    if child.type == "identifier":
                        name_node = child
                        break
        return self._text(name_node) if name_node is not None else ""

    def _mark_dynamic(self, line: int) -> None:
        """Record an unprovable dynamic construct and the line it sits on.

        Godot's ``load(computed)``, ``call(name)``, computed ``get_node`` and
        friends make liveness unprovable; the flag widens the liveness gate in
        :meth:`finish` and the collected lines feed the ``dynamic_import``
        advisory the parser reports.
        """
        self.dynamic = True
        if line and line not in self.dynamic_lines:
            self.dynamic_lines.append(line)

    def _add_node(
        self,
        name: str,
        qname: str,
        node_type: str,
        line_start: int,
        line_end: int,
        parent_id: int,
        decorators: Optional[list[str]] = None,
        type_annotation: str = "",
    ) -> int:
        info = NodeInfo(
            file_id=0,
            name=name,
            qualified_name=qname,
            node_type=node_type,
            line_start=line_start,
            line_end=line_end,
            parent_node_id=parent_id,
            decorators=list(decorators or []),
            type_annotation=type_annotation,
        )
        info.id = self._node_id
        self._node_id += 1
        self.nodes.append(info)
        return info.id

    def _add_ref(self, source_qname: str, target_name: str, edge_type: str, line: int) -> None:
        if not target_name or not source_qname:
            return
        self.references.append(
            ReferenceInfo(
                source_qname=source_qname,
                target_name=target_name,
                edge_type=edge_type,
                line=line,
            )
        )

    def _collect_member_names(self, root: Any) -> None:
        """Pre-pass: names declared at script/class level (not locals)."""

        def scan(container: Any) -> None:
            for child in container.named_children:
                node_type = child.type
                if node_type in (
                    "function_definition",
                    "constructor_definition",
                    "signal_statement",
                    "const_statement",
                    "variable_statement",
                    "enum_definition",
                    "class_definition",
                    "class_name_statement",
                ):
                    name_node = child.child_by_field_name("name")
                    if name_node is not None:
                        self.member_names.add(self._text(name_node))
                    if node_type == "class_definition":
                        for sub in child.named_children:
                            if sub.type == "class_body":
                                scan(sub)
                elif node_type == "class_body":
                    scan(child)

        scan(root)

    def _annotation_names(self, node: Any) -> list[str]:
        if node.type == "annotation":
            for child in node.named_children:
                if child.type == "identifier":
                    return ["@" + self._text(child)]
            text = self._text(node).split("(")[0].strip()
            return [text] if text else []
        names: list[str] = []
        for child in node.named_children:
            names.extend(self._annotation_names(child))
        return names

    def _prologue_annotations(self, root: Any) -> list[str]:
        """File-level annotations (``@tool``, ``@icon``) for the script root.

        Only these two annotate a GDScript *file*; every other top-level
        annotation belongs to the declaration that follows it.  Filtering
        matters: ``extends Node`` followed by ``@rpc func ping()`` must make
        ``ping`` an entry, not the whole file — attributing the annotation to
        the root would silently exempt every other member of the script.
        """
        names: list[str] = []
        for child in root.named_children:
            if child.type in ("annotation", "annotations"):
                for name in self._annotation_names(child):
                    if name in _FILE_ANNOTATIONS:
                        names.append(name)
        self._file_level_annotations = names
        return names

    def _node_annotations(self, node: Any) -> list[str]:
        """Annotations nested INSIDE a declaration node.

        ``@export var x`` / ``@onready var y`` carry the annotation in a
        leading ``annotations`` child of the ``variable_statement``, unlike
        ``@rpc func f()`` where it is a preceding sibling — both forms have to
        be collected or an exported field is never recognised as a field.
        """
        names: list[str] = []
        for child in node.named_children:
            if child.type in ("annotation", "annotations"):
                names.extend(self._annotation_names(child))
            elif child.type == "comment":
                continue
            else:
                break
        return names

    def _record_local(self, node: Any) -> None:
        """Track a function-local ``var`` so ``local.member`` can be resolved."""
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        name = self._text(name_node)
        if not name:
            return
        type_text = self._type_text(node.child_by_field_name("type"))
        if not type_text:
            type_text = self._infer_type(node.child_by_field_name("value"))
        self._local_names.add(name)
        if type_text:
            self._local_types[name] = type_text

    def _infer_type(self, value: Any) -> str:
        """Best-effort type of an initialiser (``Type.new()``, ``Type.make()``)."""
        if value is None:
            return ""
        target = value
        if value.type in ("call", "attribute_call") and value.named_children:
            target = value.named_children[0]
        if target.type == "identifier":
            base = _base_type_name(self._text(target))
            return base if base[:1].isupper() else ""
        if target.type == "attribute" and target.named_children:
            first = target.named_children[0]
            if first.type == "identifier":
                base = _base_type_name(self._text(first))
                return base if base[:1].isupper() else ""
        return ""

    def _qualified_member(self, recv_text: str, member: str) -> Optional[str]:
        """Qualified target for ``recv.member``, or None when it is unknown.

        A typed receiver (local or member) yields ``Type.member`` so the edge
        lands on the exact cross-file symbol — that is what makes
        ``player.take_damage(5)`` reach ``Player.take_damage``.  A receiver that
        is a plain value of unknown type yields ``None``: the reference stays
        silent rather than guessing a suffix match, because the resolver fails
        open (it returns every candidate) on an ambiguous suffix.  Everything
        else — enums, consts, nested classes, global type names — keeps the
        plain ``recv.member`` form.
        """
        if not recv_text or not member:
            return None
        type_text = self._local_types.get(recv_text) or self.member_types.get(
            recv_text
        )
        if type_text:
            base = _base_type_name(type_text)
            return f"{base}.{member}" if base else None
        if recv_text in self._value_names or recv_text in self._local_names:
            return None
        return f"{recv_text}.{member}"

    def _type_text(self, node: Any) -> str:
        if node is None:
            return ""
        return self._text(node)

    def _callable_name(self, node: Any) -> Optional[str]:
        if node is None:
            return None
        if node.type == "identifier":
            return self._text(node)
        if node.type == "attribute":
            children = node.named_children
            if not children:
                return None
            last = children[-1]
            if last.type == "identifier":
                return self._text(last)
            if last.type == "attribute_call" and len(children) >= 2:
                # ``method.bind(args)`` / ``method.call(args)``: the callable
                # is the link in front of the wrapper call.
                callee = next(
                    (c for c in last.named_children if c.type == "identifier"), None
                )
                if (
                    callee is not None
                    and self._text(callee) in _CALLABLE_BINDING_CALLS
                    and children[-2].type == "identifier"
                ):
                    return self._text(children[-2])
            return None
        if node.type == "call":
            children = node.named_children
            if children and self._text(children[0]) == "Callable":
                args = self._arg_nodes(
                    children[1] if len(children) > 1 else None
                )
                if len(args) > 1:
                    return self._string_value(args[1])
            return None
        return None

    def _arg_nodes(self, args: Any) -> list[Any]:
        if args is None:
            return []
        if args.type != "arguments":
            return [args]
        return list(args.named_children)

    def _string_value(self, node: Any) -> Optional[str]:
        """Return the text of a plain string literal, else ``None``.

        A StringName (``&"x"``) or a concatenation/format expression is *not*
        a plain literal, so it returns ``None`` (the caller then treats the
        value as computed).
        """
        if node is None:
            return None
        node_type = node.type
        if node_type == "string_name":
            children = node.named_children
            if len(children) == 1 and children[0].type == "string":
                return self._string_value(children[0])
            return None
        if node_type != "string":
            return None
        if len(node.named_children) > 1:
            # implicit concatenation of adjacent literals is fine; an escape
            # sequence child is fine too
            pass
        text = self._text(node)
        if not text:
            return None
        if text[0] not in ("\"", "'"):
            return None
        if len(text) < 2 or text[-1] != text[0]:
            return None
        body = text[1:-1]
        if "\\" in body:
            # an escape sequence: the adapter only accepts exact literals
            return None
        return body

    def _text(self, node: Any) -> str:
        if node is None:
            return ""
        return self.source[node.start_byte:node.end_byte].decode("utf-8", "replace")


def _basename(file_path: str) -> str:
    normalized = file_path.replace("\\", "/")
    return normalized.rsplit("/", 1)[-1] if "/" in normalized else normalized


def _base_type_name(text: str) -> str:
    """Reduce a type annotation to a plain identifier, or ``""``.

    ``Player`` → ``Player``, ``Array[Player]`` → ``Array``, ``Player?`` →
    ``Player``; anything that is not a simple dotted identifier (a callable
    type, a union, a literal type) yields ``""`` so the caller stays silent.
    """
    text = (text or "").strip().rstrip("?")
    if not text:
        return ""
    bracket = text.find("[")
    if bracket != -1:
        text = text[:bracket].strip()
    if not text:
        return ""
    for char in text:
        if not (char.isalnum() or char in "_.:"):
            return ""
    return text


def _script_node_type(file_path: str) -> str:
    from .constants import (
        NODE_PROJECT,
        NODE_RESOURCE,
        NODE_SCENE,
        NODE_SCRIPT,
        _is_project_manifest,
        _is_resource_file,
        _is_scene_file,
    )

    if _is_project_manifest(file_path):
        return NODE_PROJECT
    if _is_scene_file(file_path):
        return NODE_SCENE
    if _is_resource_file(file_path):
        return NODE_RESOURCE
    return NODE_SCRIPT
