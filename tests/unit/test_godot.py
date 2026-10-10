# -*- coding: utf-8 -*-
"""Tests for the Godot/GDScript language adapter — constants, adapter wiring,
the tree-sitter visitor and the ``.gd`` parser."""

from __future__ import annotations

import pickle
from typing import Any

import pytest

from graphlint.analyzer.language.godot import GodotAdapter, build_adapter
from graphlint.analyzer.language.godot.constants import (
    NODE_CLASS,
    NODE_CONSTANT,
    NODE_ENUM,
    NODE_ENUM_MEMBER,
    NODE_FIELD,
    NODE_FUNCTION,
    NODE_SIGNAL,
    NODE_VARIABLE,
    _GODOT_DEFAULT_EXCLUDES,
    _GODOT_EXTENSIONS,
    _GODOT_SPECIAL_NAMES,
    _TREE_SITTER_GDSCRIPT_AVAILABLE,
    _file_to_module,
    _is_gd_file,
    _is_godot_file,
    _is_project_manifest,
    _is_resource_file,
    _is_scene_file,
    _is_test_file,
    _to_res_path,
)
from graphlint.analyzer.language.godot.gd_parser import parse_gd

gdscript = pytest.mark.skipif(
    not _TREE_SITTER_GDSCRIPT_AVAILABLE, reason="tree-sitter-gdscript not installed"
)


def _by_type(result: Any, node_type: str) -> list[Any]:
    return [n for n in result.nodes if n.node_type == node_type]


def _names(result: Any) -> set[str]:
    return {n.name for n in result.nodes}


def _qname_of(result: Any, name: str, node_type: str | None = None) -> str:
    for node in result.nodes:
        if node.name == name and (node_type is None or node.node_type == node_type):
            return node.qualified_name
    raise AssertionError(f"no node {name!r} ({node_type}) in {sorted(_names(result))}")


def _refs(result: Any, edge_type: str | None = None) -> list[Any]:
    refs = list(result.references)
    if edge_type is not None:
        refs = [r for r in refs if r.edge_type == edge_type]
    return refs


def _targets(result: Any, edge_type: str | None = None) -> list[str]:
    return [r.target_name for r in _refs(result, edge_type)]


def _warning_types(result: Any) -> set[str]:
    return {w.warn_type for w in result.warnings}


# =============================================================================
# constants / file classification (always runnable)
# =============================================================================


class TestGodotConstants:
    def test_extension_sets(self):
        assert _is_gd_file("scripts/player.gd") is True
        assert _is_scene_file("scenes/world.tscn") is True
        assert _is_resource_file("assets/data.tres") is True
        assert _is_project_manifest("project.godot") is True
        assert _is_godot_file("project.godot") is True
        assert _is_godot_file("scripts/player.gd") is True
        assert _is_godot_file("src/app.py") is False
        assert _is_godot_file("shaders/x.gdshader") is False
        assert _GODOT_EXTENSIONS == frozenset({".gd", ".tscn", ".tres", ".godot"})

    def test_file_to_module_uses_res_scheme(self):
        assert _file_to_module("scripts/player.gd") == "res://scripts/player.gd"
        assert _file_to_module("scripts\\player.gd") == "res://scripts/player.gd"
        assert _to_res_path("scenes/world.tscn") == "res://scenes/world.tscn"
        # an already-absolute res:// path stays untouched
        assert _to_res_path("res://a/b.gd") == "res://a/b.gd"

    def test_default_excludes_is_empty_on_purpose(self):
        """Godot's cache dirs are dot-directories the scanner already prunes, and
        directory excludes are matched by basename and unioned across adapters."""
        assert _GODOT_DEFAULT_EXCLUDES == frozenset()

    def test_node_type_mapping_is_liveness_compatible(self):
        # ``event`` and ``class`` are in the core's _READ_PROMOTED_TYPES, which is
        # what lets an owner->member keep-alive read edge propagate reachability.
        assert NODE_SIGNAL == "event"
        assert NODE_CLASS == "class"
        # ``variable`` is promoted by the core's adjacent variable/field rule and
        # is inspected by detect_write_only_nodes, so an unread const is reported.
        assert NODE_CONSTANT == "variable"
        assert NODE_VARIABLE == "variable"
        assert NODE_FIELD == "field"
        assert NODE_FUNCTION == "function"

    def test_engine_virtuals_are_special(self):
        assert "_ready" in _GODOT_SPECIAL_NAMES
        assert "_process" in _GODOT_SPECIAL_NAMES
        assert "_physics_process" in _GODOT_SPECIAL_NAMES
        assert "take_damage" not in _GODOT_SPECIAL_NAMES

    def test_is_test_file_patterns(self):
        empty: dict[str, Any] = {}
        assert _is_test_file("scripts/test_player.gd", empty) is True
        assert _is_test_file("scripts/player_test.gd", empty) is True
        assert _is_test_file("tests/player.gd", empty) is True
        assert _is_test_file("test/unit/player.gd", empty) is True
        assert _is_test_file("scripts/player.gd", empty) is False
        # configured patterns are honoured as well
        cfg = {"test_patterns": {"file_patterns": ["*_probe.gd"]}}
        assert _is_test_file("scripts/x_probe.gd", cfg) is True


# =============================================================================
# adapter wiring
# =============================================================================


class TestGodotAdapter:
    def test_adapter_surface(self):
        adapter = GodotAdapter()
        assert adapter.language_name == "godot"
        assert adapter.file_extensions == _GODOT_EXTENSIONS
        assert adapter.file_to_module("scripts/player.gd") == "res://scripts/player.gd"
        assert adapter.default_excludes == frozenset()
        assert adapter.public_api_names == frozenset()
        assert adapter.is_special_name("_ready") is True
        assert adapter.is_special_name("_on_button_pressed") is True  # _on_ prefix
        assert adapter.is_special_name("take_damage") is False

    def test_build_adapter_registers_all_extensions(self):
        adapter = build_adapter()
        assert isinstance(adapter, GodotAdapter)
        assert adapter.file_extensions == _GODOT_EXTENSIONS

    def test_worker_function_is_module_level_and_picklable(self):
        """The indexer ships this callable to worker processes: a bound method or
        closure would fail to pickle."""
        adapter = build_adapter()
        worker = adapter.worker_function
        assert callable(worker)
        assert getattr(worker, "__module__", "").endswith("godot.parser")
        assert pickle.loads(pickle.dumps(worker)) is worker

    @gdscript
    def test_parse_file_dispatches_by_extension(self, tmp_path):
        (tmp_path / "scripts").mkdir()
        (tmp_path / "scripts" / "player.gd").write_text(
            "extends Node\nfunc _ready():\n\tpass\n", encoding="utf-8"
        )
        (tmp_path / "scenes.tscn").write_text(
            '[gd_scene format=3]\n[node name="World" type="Node2D"]\n', encoding="utf-8"
        )
        (tmp_path / "project.godot").write_text(
            '[application]\nrun/main_scene="res://scenes.tscn"\n', encoding="utf-8"
        )
        adapter = build_adapter()

        script = adapter.parse_file(str(tmp_path / "scripts" / "player.gd"), str(tmp_path), {})
        scene = adapter.parse_file(str(tmp_path / "scenes.tscn"), str(tmp_path), {})
        manifest = adapter.parse_file(str(tmp_path / "project.godot"), str(tmp_path), {})

        assert script.file_path == "scripts/player.gd"
        assert script.nodes[0].node_type == "script"
        assert scene.file_path == "scenes.tscn"
        assert scene.nodes[0].node_type == "scene"
        assert manifest.file_path == "project.godot"
        assert manifest.nodes[0].node_type == "project"

    def test_missing_file_degrades_to_a_warning(self, tmp_path):
        adapter = build_adapter()
        result = adapter.parse_file(str(tmp_path / "nope.gd"), str(tmp_path), {})
        assert result.nodes == []
        assert "syntax_error" in _warning_types(result)


# =============================================================================
# ``.gd`` declarations
# =============================================================================


@gdscript
class TestGdDeclarations:
    SRC = '''class_name Player
extends CharacterBody2D

signal died(reason: String)

const MAX_HEALTH: int = 100

enum State { IDLE, RUN }

@export var speed: float = 120.0
@onready var sprite: Sprite2D = $Sprite
var health: int = MAX_HEALTH

class Inner:
\tvar x: int = 1

func take_damage(amount: int) -> void:
\thealth -= amount
\tdied.emit("dead")

func _ready() -> void:
\tprint(health)
'''

    def test_declarations_become_nodes(self):
        result = parse_gd("scripts/player.gd", self.SRC, {})
        assert _qname_of(result, "Player", NODE_CLASS) == "res://scripts/player.gd.Player"
        assert _qname_of(result, "died", NODE_SIGNAL) == "res://scripts/player.gd.Player.died"
        assert _qname_of(result, "MAX_HEALTH", NODE_CONSTANT) == (
            "res://scripts/player.gd.Player.MAX_HEALTH"
        )
        assert _qname_of(result, "State", NODE_ENUM) == "res://scripts/player.gd.Player.State"
        assert _qname_of(result, "IDLE", NODE_ENUM_MEMBER) == (
            "res://scripts/player.gd.Player.State.IDLE"
        )
        assert _qname_of(result, "Inner", NODE_CLASS) == "res://scripts/player.gd.Player.Inner"
        assert _qname_of(result, "take_damage", NODE_FUNCTION) == (
            "res://scripts/player.gd.Player.take_damage"
        )

    def test_declared_types_are_recorded(self):
        result = parse_gd("scripts/player.gd", self.SRC, {})
        by_name = {n.name: n for n in result.nodes}
        assert by_name["MAX_HEALTH"].type_annotation == "int"
        assert by_name["speed"].type_annotation == "float"
        assert by_name["sprite"].type_annotation == "Sprite2D"
        assert by_name["take_damage"].type_annotation == "void"

    def test_export_and_onready_are_fields_others_are_variables(self):
        result = parse_gd("scripts/player.gd", self.SRC, {})
        by_name = {n.name: n for n in result.nodes}
        # @export / @onready are engine-visible properties
        assert by_name["speed"].node_type == NODE_FIELD
        assert by_name["sprite"].node_type == NODE_FIELD
        assert by_name["speed"].decorators == ["@export"]
        assert by_name["sprite"].decorators == ["@onready"]
        # a plain member variable is not a field
        assert by_name["health"].node_type == NODE_VARIABLE

    def test_extends_emits_inherit_and_read(self):
        result = parse_gd("scripts/player.gd", self.SRC, {})
        assert "CharacterBody2D" in _targets(result, "inherit")
        # the read edge is what lets reachability flow to the base class file
        assert "CharacterBody2D" in _targets(result, "read")

    def test_extends_by_path_becomes_an_import(self):
        result = parse_gd(
            "scripts/enemy.gd", 'extends "res://actors/base.gd"\n', {}
        )
        assert [(i.path, i.kind) for i in result.imports] == [
            ("res://actors/base.gd", "extends")
        ]
        assert "res://actors/base.gd" in _targets(result, "inherit")
        assert "res://actors/base.gd" in _targets(result, "read")

    def test_constructor_definition_is_a_function_named_init(self):
        result = parse_gd(
            "scripts/x.gd", "extends Node\nfunc _init() -> void:\n\tpass\n", {}
        )
        assert "_init" in _names(result)
        assert "_init" in _GODOT_SPECIAL_NAMES


# =============================================================================
# references: dotted members, locals, dispatch
# =============================================================================


@gdscript
class TestGdReferences:
    def test_typed_member_call_resolves_to_type_member(self):
        """``player.take_damage(5)`` must target ``Player.take_damage``: the plain
        dotted string never resolves in the core's symbol index."""
        result = parse_gd(
            "scripts/level.gd",
            'extends Node2D\n'
            '@onready var player: Player = $Player\n'
            'func _on_button_pressed() -> void:\n'
            '\tplayer.take_damage(5)\n',
            {},
        )
        calls = _targets(result, "call")
        assert "Player.take_damage" in calls
        assert "player.take_damage" not in calls
        assert "player" in _targets(result, "read")

    def test_local_typed_call_is_resolved(self):
        result = parse_gd(
            "scripts/level.gd",
            'extends Node2D\n'
            'func go() -> void:\n'
            '\tvar t: TypeRefOnly = TypeRefOnly.new()\n'
            '\tprint(t.payload)\n',
            {},
        )
        assert "TypeRefOnly.new" in _targets(result, "call")
        assert "TypeRefOnly.payload" in _targets(result, "read")

    def test_untyped_receiver_stays_silent(self):
        """An unknown receiver type must not guess a target: the core resolver
        fails open on ambiguous suffix matches."""
        result = parse_gd(
            "scripts/x.gd",
            "extends Node\nfunc go(thing) -> void:\n\tthing.take_damage(1)\n",
            {},
        )
        assert _targets(result, "call") == []
        assert "thing" in _targets(result, "read")

    def test_typed_parameter_resolves(self):
        result = parse_gd(
            "scripts/x.gd",
            "extends Node\n"
            "func hit(target: Player, tag = null) -> void:\n"
            "\ttarget.take_damage(1)\n",
            {},
        )
        assert "Player.take_damage" in _targets(result, "call")

    def test_self_and_super_calls(self):
        result = parse_gd(
            "scripts/x.gd",
            "extends Node\n"
            "func a() -> void:\n\tb()\n"
            "func b() -> void:\n\tsuper.b()\n",
            {},
        )
        calls = _targets(result, "call")
        # a bare call is resolved by the core's suffix index (single match)
        assert "b" in calls
        # ``super`` is qualified by the declared base type
        assert "Node.b" in calls

    def test_literal_string_dispatch_is_kept_alive(self):
        result = parse_gd(
            "scripts/game_state.gd",
            "extends Node\n"
            "var score: int = 0\n"
            "func add_score(n: int) -> void:\n\tscore += n\n"
            "func go() -> void:\n\tcall(\"add_score\", 1)\n",
            {},
        )
        assert "add_score" in getattr(result, "godot_dispatch_names")
        assert "res://scripts/game_state.gd.add_score" in _targets(result, "call")

    def test_computed_load_marks_the_file_dynamic(self):
        result = parse_gd(
            "scripts/x.gd",
            "extends Node\nfunc go(path: String) -> void:\n\tload(path)\n",
            {},
        )
        assert getattr(result, "godot_dynamic") is True
        assert "dynamic_import" in _warning_types(result)
        assert getattr(result, "godot_dynamic_lines") == [3]

    def test_computed_property_name_keeps_only_data_alive(self):
        """``dict.get(key, default)`` is a data lookup, not an unprovable
        dispatch: the file stays provable, so method-level dead code still
        works, while the data members the name could reach are kept alive."""
        src = (
            "extends Node\n"
            "var stored: int = 0\n"
            "func go(key: String) -> void:\n"
            "\tvar registry: Dictionary = {}\n"
            "\tregistry.get(key, 0)\n"
            "func never_called() -> void:\n"
            "\tpass\n"
        )
        result = parse_gd("scripts/x.gd", src, {"godot": {"method_dead_code": True}})
        assert getattr(result, "godot_dynamic") is False
        assert "dynamic_import" not in _warning_types(result)
        # the computed property name could be "stored" ...
        assert "res://scripts/x.gd.stored" in _targets(result, "read")
        # ... but it can never be a method name
        assert "res://scripts/x.gd.never_called" not in _targets(result, "read")

    def test_computed_method_name_keeps_functions_alive(self):
        src = (
            "extends Node\n"
            "func go(action: Callable) -> void:\n"
            "\taction.call()\n"
            "func maybe_called() -> void:\n"
            "\tpass\n"
        )
        result = parse_gd("scripts/x.gd", src, {"godot": {"method_dead_code": True}})
        assert getattr(result, "godot_dynamic") is False
        assert "res://scripts/x.gd.maybe_called" in _targets(result, "read")

    def test_computed_signal_name_keeps_signals_alive(self):
        src = (
            "extends Node\n"
            "signal died\n"
            "func go(which: String) -> void:\n"
            "\temit_signal(which)\n"
        )
        result = parse_gd("scripts/x.gd", src, {"godot": {"signal_dead_code": True}})
        assert getattr(result, "godot_dynamic") is False
        assert "res://scripts/x.gd.died" in _targets(result, "read")

    def test_literal_dispatch_name_of_another_file_is_not_dynamic(self):
        """A literal name that is not a member of this file belongs to the
        project-wide dispatch pass — it must not make this file unprovable."""
        src = (
            "extends Node\n"
            "func go() -> void:\n"
            '\tcall("other_script_method")\n'
            "func never_called() -> void:\n"
            "\tpass\n"
        )
        result = parse_gd("scripts/x.gd", src, {"godot": {"method_dead_code": True}})
        assert getattr(result, "godot_dynamic") is False
        assert "other_script_method" in getattr(result, "godot_dispatch_names")
        assert "res://scripts/x.gd.never_called" not in _targets(result, "read")

    def test_literal_load_is_a_static_dependency(self):
        result = parse_gd(
            "scripts/x.gd",
            'extends Node\n'
            'const COIN = preload("res://scenes/coin.tscn")\n'
            'func go() -> void:\n\tprint(COIN)\n',
            {},
        )
        assert getattr(result, "godot_dynamic") is False
        assert [(i.path, i.kind, i.name) for i in result.imports] == [
            ("res://scenes/coin.tscn", "preload", "COIN")
        ]
        assert "res://scenes/coin.tscn" in _targets(result, "read")
        assert "unused_import" not in _warning_types(result)

    def test_unused_preload_is_reported(self):
        result = parse_gd(
            "scripts/x.gd",
            'extends Node\nconst COIN = preload("res://scenes/coin.tscn")\n',
            {},
        )
        assert "unused_import" in _warning_types(result)

    def test_syntax_error_is_reported(self):
        result = parse_gd("scripts/broken.gd", "func f(:\n", {})
        assert "syntax_error" in _warning_types(result)

    def test_engine_type_error_is_not_a_parse_error(self):
        """A type error is the engine's job — tree-sitter parses it cleanly and
        the adapter must not pretend to type-check."""
        result = parse_gd(
            "scripts/broken.gd",
            'extends Node\nfunc f() -> void:\n\tvar x: int = "oops"\n',
            {},
        )
        assert "syntax_error" not in _warning_types(result)
        assert "f" in _names(result)


# =============================================================================
# visitor liveness flags
# =============================================================================


@gdscript
class TestGdLivenessFlags:
    def test_signal_kept_alive_by_default(self):
        """``signal_dead_code`` defaults to False, so a declared signal gets a
        keep-alive read edge and can never be judged dead."""
        result = parse_gd(
            "scripts/x.gd", "extends Node\nsignal died\nfunc go() -> void:\n\tpass\n", {}
        )
        assert "res://scripts/x.gd.died" in _targets(result, "read")

    def test_signal_dead_code_opt_in(self):
        result = parse_gd(
            "scripts/x.gd",
            "extends Node\nsignal died\nfunc go() -> void:\n\tpass\n",
            {"godot": {"signal_dead_code": True}},
        )
        assert "res://scripts/x.gd.died" not in _targets(result, "read")

    def test_method_dead_code_is_opt_in(self):
        src = "extends Node\nfunc never_called() -> void:\n\tpass\n"
        lax = parse_gd("scripts/x.gd", src, {})
        strict = parse_gd("scripts/x.gd", src, {"godot": {"method_dead_code": True}})
        assert "res://scripts/x.gd.never_called" in _targets(lax, "read")
        assert "res://scripts/x.gd.never_called" not in _targets(strict, "read")

    def test_fields_follow_their_owner(self):
        result = parse_gd(
            "scripts/x.gd", "extends Node\n@export var speed: float = 1.0\n", {}
        )
        assert "res://scripts/x.gd.speed" in _targets(result, "read")

    def test_dynamic_gate_can_be_disabled(self):
        src = (
            'extends Node\nfunc go(path: String) -> void:\n\tload(path)\n'
            "func never_called() -> void:\n\tpass\n"
        )
        strict = {"godot": {"method_dead_code": True}}
        gated = parse_gd("scripts/x.gd", src, strict)
        ungated = parse_gd(
            "scripts/x.gd",
            src,
            {"godot": {"method_dead_code": True, "assume_dynamic_keeps_file_alive": False}},
        )
        # the dynamic construct is detected either way ...
        assert getattr(gated, "godot_dynamic") is True
        assert getattr(ungated, "godot_dynamic") is True
        # ... and it is the gate that decides whether the whole file is kept alive
        assert "res://scripts/x.gd.never_called" in _targets(gated, "read")
        assert "res://scripts/x.gd.never_called" not in _targets(ungated, "read")
