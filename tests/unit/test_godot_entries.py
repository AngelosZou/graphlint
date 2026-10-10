# -*- coding: utf-8 -*-
"""Tests for Godot entry detection and the end-to-end graph verdict.

The entry surface is what decides every dead-code verdict, so it is pinned
twice: once against hand-built parse results, and once end to end through
``GraphBuilder`` on a small Godot project written to ``tmp_path``.
"""

from __future__ import annotations

import copy
import os

import pytest

from graphlint.analyzer._types import NodeInfo, ParseResult
from graphlint.analyzer.language.godot.constants import (
    NODE_FUNCTION,
    NODE_SCRIPT,
)
from graphlint.analyzer.language.godot.entry import (
    GdEntryPointDetector,
    _match_path,
)
from graphlint.analyzer.language.godot.gd_parser import parse_gd
from graphlint.analyzer.language.godot.project_parser import parse_project
from graphlint.analyzer.language.godot.resource_parser import parse_resource
from graphlint.config.defaults import DEFAULT_CONFIG

try:
    from graphlint.analyzer.language.godot.constants import (
        _TREE_SITTER_GDSCRIPT_AVAILABLE,
    )
except ImportError:  # pragma: no cover - defensive
    _TREE_SITTER_GDSCRIPT_AVAILABLE = False

gdscript = pytest.mark.skipif(
    not _TREE_SITTER_GDSCRIPT_AVAILABLE,
    reason="tree-sitter-gdscript not installed",
)


def _config(overrides: dict | None = None) -> dict:
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    for key, value in (overrides or {}).items():
        if isinstance(value, dict) and isinstance(cfg.get(key), dict):
            merged = dict(cfg[key])
            merged.update(value)
            cfg[key] = merged
        else:
            cfg[key] = value
    return cfg


def _detect(files: dict[str, str], overrides: dict | None = None):
    """Parse ``files`` and mimic the core's global node-id assignment."""
    cfg = _config(overrides)
    prs: dict[str, ParseResult] = {}
    for path, source in files.items():
        if path.endswith(".gd"):
            prs[path] = parse_gd(path, source, cfg)
        elif path.endswith(".tscn"):
            prs[path] = parse_resource(path, source, cfg)
        elif path.endswith(".tres"):
            prs[path] = parse_resource(path, source, cfg)
        else:
            prs[path] = parse_project(path, source, cfg)

    nodes: list[NodeInfo] = []
    for pr in prs.values():
        nodes.extend(pr.nodes)
    for index, node in enumerate(nodes, start=1):
        node.id = index
    node_id_map = {node.id: node for node in nodes}

    entries = GdEntryPointDetector(cfg).detect(prs, nodes, node_id_map)
    return entries, prs, nodes, node_id_map


def _rules(entries) -> list[str]:
    return [e.rule_name for e in entries]


def _by_rule(entries, rule_name):
    return [e for e in entries if e.rule_name == rule_name]


class TestMatchPath:
    def test_direct_match(self):
        assert _match_path("scripts/x.gd", "scripts/*.gd")

    def test_root_retry_strips_the_leading_globstar(self):
        # ``fnmatch``'s ``*`` crosses separators, so the retry is what makes a
        # bare file name pattern match a nested path *and* the root one
        assert _match_path("project.godot", "**/project.godot")
        assert _match_path("sub/dir/project.godot", "**/project.godot")
        assert not _match_path("scripts/x.gd", "**/project.godot")

    def test_non_matching(self):
        assert not _match_path("scripts/x.gd", "**/*.tscn")


@gdscript
class TestEntryRules:
    def test_project_manifest_is_an_entry(self):
        entries, _prs, nodes, _map = _detect(
            {"project.godot": '[application]\nrun/main_scene="res://scenes/l.tscn"\n'}
        )
        project = _by_rule(entries, "godot_project")
        assert len(project) == 1
        assert project[0].no_propagate is False
        # node_id 0 is a file-scope entry: every node of the manifest is an entry
        assert project[0].node_id == 0
        assert len(nodes) == 1

    def test_project_manifest_rule_matches_by_file_name(self):
        entries, _prs, _nodes, _map = _detect(
            {"sub/dir/project.godot": "[application]\nconfig/name=\"x\"\n"}
        )
        assert "godot_project" in _rules(entries)

    def test_tool_script_is_an_entry(self):
        entries, _prs, nodes, _map = _detect(
            {"scripts/tool_plugin.gd": "@tool\nextends EditorPlugin\n"}
        )
        tool = _by_rule(entries, "godot_editor_tool")
        assert len(tool) == 1
        root = [n for n in nodes if n.node_type == NODE_SCRIPT][0]
        assert tool[0].node_id == root.id

    def test_rpc_method_is_an_entry(self):
        entries, _prs, nodes, _map = _detect(
            {"scripts/net.gd": "extends Node\n\n@rpc\nfunc ping() -> void:\n\tpass\n"}
        )
        rpc = _by_rule(entries, "godot_rpc_method")
        assert len(rpc) == 1
        ping = [n for n in nodes if n.name == "ping"][0]
        assert rpc[0].node_id == ping.id

    def test_test_script_is_an_entry_with_no_propagate(self):
        entries, _prs, _nodes, _map = _detect(
            {"tests/test_player.gd": "extends Node\n\nfunc test_one() -> void:\n\tpass\n"}
        )
        tests = _by_rule(entries, "godot_test")
        assert len(tests) == 1
        assert tests[0].no_propagate is True

    def test_public_class_is_an_entry(self):
        entries, _prs, nodes, _map = _detect(
            {"scripts/player.gd": "class_name Player\nextends Node\n"}
        )
        public = _by_rule(entries, "godot_public_class")
        assert len(public) == 1
        assert "Player" in public[0].description
        owners = [n for n in nodes if n.qualified_name.endswith(".Player")]
        assert owners and public[0].node_id == owners[0].id

    def test_public_class_can_be_disabled(self):
        entries, _prs, _nodes, _map = _detect(
            {"scripts/player.gd": "class_name Player\nextends Node\n"},
            {"godot": {"public_class_api": False}},
        )
        assert _by_rule(entries, "godot_public_class") == []

    def test_plain_script_is_not_a_public_class_entry(self):
        entries, _prs, _nodes, _map = _detect(
            {"scripts/plain.gd": "extends Node\n"}
        )
        assert _by_rule(entries, "godot_public_class") == []

    def test_disabled_rule_is_skipped(self):
        cfg = _config()
        cfg["entry_rules"] = [
            {**rule, "enabled": False} if rule["name"] == "godot_editor_tool" else rule
            for rule in cfg["entry_rules"]
        ]
        prs = {"scripts/t.gd": parse_gd("scripts/t.gd", "@tool\nextends Node\n", cfg)}
        nodes = list(prs["scripts/t.gd"].nodes)
        for index, node in enumerate(nodes, start=1):
            node.id = index
        entries = GdEntryPointDetector(cfg).detect(prs, nodes, {n.id: n for n in nodes})
        assert "godot_editor_tool" not in _rules(entries)

    def test_foreign_extensions_are_ignored(self):
        entries, _prs, nodes, node_id_map = _detect(
            {"project.godot": '[application]\nconfig/name="x"\n'}
        )
        foreign = ParseResult(file_path="scripts/thing.py")
        foreign.nodes = [
            NodeInfo(
                name="_ready",
                qualified_name="scripts/thing.py._ready",
                node_type=NODE_FUNCTION,
                line_start=1,
            )
        ]
        nodes.extend(foreign.nodes)
        foreign.nodes[0].id = 99
        node_id_map[99] = foreign.nodes[0]
        more = GdEntryPointDetector(_config()).detect(
            {"scripts/thing.py": foreign}, nodes, node_id_map
        )
        assert more == []


@gdscript
class TestDispatchKeepAlive:
    def test_literal_call_keeps_a_cross_file_member_alive(self):
        entries, _prs, nodes, _map = _detect(
            {
                "scripts/game_state.gd": (
                    "extends Node\n\nfunc add_score(n: int) -> void:\n\tpass\n"
                ),
                "scripts/ui.gd": (
                    'extends Node\n\nfunc bump() -> void:\n\tget_node("/root/GameState").call("add_score", 1)\n'
                ),
            }
        )
        dispatch = _by_rule(entries, "godot_dynamic_dispatch")
        assert dispatch, _rules(entries)
        add_score = [n for n in nodes if n.name == "add_score"][0]
        assert any(e.node_id == add_score.id for e in dispatch)

    def test_connection_method_keeps_the_handler_alive(self):
        entries, _prs, nodes, _map = _detect(
            {
                "scripts/level.gd": (
                    "extends Node2D\n\nfunc _on_button_pressed() -> void:\n\tpass\n"
                ),
                "scenes/level.tscn": (
                    "[gd_scene format=3]\n"
                    "\n"
                    '[ext_resource type="Script" path="res://scripts/level.gd" id="1"]\n'
                    "\n"
                    '[node name="Level" type="Node2D"]\n'
                    'script = ExtResource("1")\n'
                    "\n"
                    '[connection signal="pressed" from="Level/B" to="Level" '
                    'method="_on_button_pressed"]\n'
                ),
            }
        )
        dispatch = _by_rule(entries, "godot_dynamic_dispatch")
        handler = [n for n in nodes if n.name == "_on_button_pressed"][0]
        assert any(e.node_id == handler.id for e in dispatch)

    def test_keep_alive_can_be_disabled(self):
        entries, _prs, _nodes, _map = _detect(
            {
                "scripts/game_state.gd": "extends Node\n\nfunc add_score() -> void:\n\tpass\n",
                "scripts/ui.gd": 'extends Node\n\nfunc bump() -> void:\n\tcall("add_score")\n',
            },
            {"godot": {"dispatch_keepalive": False}},
        )
        assert _by_rule(entries, "godot_dynamic_dispatch") == []

    def test_unknown_dispatch_name_produces_nothing(self):
        entries, _prs, _nodes, _map = _detect(
            {
                "scripts/game_state.gd": "extends Node\n\nfunc add_score() -> void:\n\tpass\n",
                "scripts/ui.gd": 'extends Node\n\nfunc bump() -> void:\n\tcall("nowhere")\n',
            }
        )
        assert _by_rule(entries, "godot_dynamic_dispatch") == []

    def test_godot4_connect_keeps_the_handler_alive(self):
        """``button.pressed.connect(_on_pressed)`` names the handler."""
        entries, prs, nodes, _map = _detect(
            {
                "scripts/panel.gd": (
                    "extends Node\n"
                    "\n"
                    "signal pressed\n"
                    "\n"
                    "func _on_pressed() -> void:\n"
                    "\tpass\n"
                    "\n"
                    "func wire(button: Button) -> void:\n"
                    "\tbutton.pressed.connect(_on_pressed)\n"
                ),
            }
        )
        dispatch = _by_rule(entries, "godot_dynamic_dispatch")
        handler = [n for n in nodes if n.name == "_on_pressed"][0]
        assert any(e.node_id == handler.id for e in dispatch)
        # the signal end of the chain is named too
        signal = [n for n in nodes if n.name == "pressed"][0]
        assert any(e.node_id == signal.id for e in dispatch)

    def test_bound_method_connect_names_the_callable(self):
        """``go.bind(title)`` resolves to the method ``go``."""
        entries, _prs, nodes, _map = _detect(
            {
                "scripts/router.gd": (
                    "extends Node\n"
                    "\n"
                    "func go(title: String) -> void:\n"
                    "\tpass\n"
                    "\n"
                    "func wire(button: Button, title: String) -> void:\n"
                    "\tbutton.pressed.connect(go.bind(title))\n"
                ),
            }
        )
        target = [n for n in nodes if n.name == "go"][0]
        dispatch = _by_rule(entries, "godot_dynamic_dispatch")
        assert any(e.node_id == target.id for e in dispatch)

    def test_godot4_connect_does_not_mark_the_file_dynamic(self):
        """A resolvable connection is not an unprovable construct."""
        _entries, prs, _nodes, _map = _detect(
            {
                "scripts/panel.gd": (
                    "extends Node\n"
                    "\n"
                    "signal pressed\n"
                    "\n"
                    "func _on_pressed() -> void:\n"
                    "\tpass\n"
                    "\n"
                    "func wire(button: Button) -> void:\n"
                    "\tbutton.pressed.connect(_on_pressed)\n"
                ),
            }
        )
        kinds = [w.warn_type for w in prs["scripts/panel.gd"].warnings]
        assert "dynamic_import" not in kinds, kinds

    def test_connect_with_no_known_end_is_still_dynamic(self):
        """A computed receiver *and* a computed callable stay unprovable."""
        _entries, prs, _nodes, _map = _detect(
            {
                "scripts/panel.gd": (
                    "extends Node\n"
                    "\n"
                    "func wire(ends: Array) -> void:\n"
                    "\tends[0].connect(ends[1])\n"
                ),
            }
        )
        kinds = [w.warn_type for w in prs["scripts/panel.gd"].warnings]
        assert "dynamic_import" in kinds, kinds


@gdscript
class TestGodotEndToEnd:
    """The plan's acceptance fixture: the four verdicts plus cross-file refs."""

    PROJECT = (
        "config_version=5\n"
        "\n"
        "[application]\n"
        "\n"
        'config/name="E2E"\n'
        'run/main_scene="res://scenes/level.tscn"\n'
        "\n"
        "[autoload]\n"
        "\n"
        'GameState="*res://scripts/game_state.gd"\n'
    )

    LEVEL_GD = (
        "extends Node2D\n"
        "\n"
        "@onready var player: Player = $Player\n"
        "\n"
        "func _ready() -> void:\n"
        "\tprint(player)\n"
        "\n"
        "func _on_button_pressed() -> void:\n"
        "\tplayer.take_damage(5)\n"
    )

    PLAYER_GD = (
        "class_name Player\n"
        "extends CharacterBody2D\n"
        "\n"
        "signal died(reason: String)\n"
        "\n"
        "var health: int = 100\n"
        "\n"
        "func take_damage(amount: int) -> void:\n"
        "\thealth -= amount\n"
        '\tdied.emit("dead")\n'
        "\n"
        "func never_called() -> void:\n"
        "\tpass\n"
    )

    LEVEL_TSCN = (
        "[gd_scene load_steps=2 format=3]\n"
        "\n"
        '[ext_resource type="Script" path="res://scripts/level.gd" id="1_level"]\n'
        "\n"
        '[node name="Level" type="Node2D"]\n'
        'script = ExtResource("1_level")\n'
        "\n"
        '[connection signal="pressed" from="Level/Button" to="Level" '
        'method="_on_button_pressed"]\n'
    )

    GAME_STATE_GD = "extends Node\n\nvar score: int = 0\n\nfunc add_score(n: int) -> void:\n\tscore += n\n"

    ORPHAN_GD = "extends Node\n\nfunc lonely() -> void:\n\tpass\n"

    ORPHAN_TSCN = '[gd_scene format=3]\n\n[node name="Orphan" type="Node"]\n'

    BROKEN_TSCN = (
        "[gd_scene format=3]\n"
        "\n"
        '[ext_resource type="Script" path="res://scripts/ghost.gd" id="1_ghost"]\n'
        "\n"
        '[node name="Broken" type="Node"]\n'
        'script = ExtResource("1_ghost")\n'
    )

    @pytest.fixture()
    def project(self, tmp_path):
        files = {
            "project.godot": self.PROJECT,
            "scripts/level.gd": self.LEVEL_GD,
            "scripts/player.gd": self.PLAYER_GD,
            "scripts/game_state.gd": self.GAME_STATE_GD,
            "scripts/orphan.gd": self.ORPHAN_GD,
            "scenes/level.tscn": self.LEVEL_TSCN,
            "scenes/orphan.tscn": self.ORPHAN_TSCN,
            "scenes/broken.tscn": self.BROKEN_TSCN,
        }
        for rel, source in files.items():
            target = tmp_path / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(source, encoding="utf-8")
        return tmp_path

    def _build(self, root, overrides=None):
        from graphlint.api import _build_registry
        from graphlint.analyzer.graph import GraphBuilder
        from graphlint.analyzer.warnings import WarningCollector

        cfg = _config(overrides)
        cfg["_root_dir"] = str(root)
        registry = _build_registry()
        prs = {}
        for rel, _mtime in registry.scan_files(str(root)):
            adapter = registry.adapter_for_file(rel)
            if adapter is None:
                continue
            prs[rel] = adapter.parse_file(os.path.join(str(root), rel), str(root), cfg)
        result = GraphBuilder(
            WarningCollector(), registry=registry, config=cfg
        ).build(prs)
        return result

    def _id_of(self, result, qname):
        for node in result.nodes:
            if node.qualified_name == qname:
                return node.id
        raise AssertionError(
            "node not found: "
            + qname
            + "\n"
            + "\n".join(sorted(n.qualified_name for n in result.nodes))
        )

    def _dead_qnames(self, result):
        dead = set()
        for comp in result.components:
            if not comp.is_dead_code:
                continue
            for nid in comp.node_ids:
                node = result.node_id_map.get(nid)
                if node is not None:
                    dead.add(node.qualified_name)
        return dead

    def test_adapter_parses_every_project_file(self, project):
        result = self._build(project)
        assert set(result.files) == {
            "project.godot",
            "scripts/level.gd",
            "scripts/player.gd",
            "scripts/game_state.gd",
            "scripts/orphan.gd",
            "scenes/level.tscn",
            "scenes/orphan.tscn",
            "scenes/broken.tscn",
        }

    def test_call_edge_makes_the_method_alive(self, project):
        result = self._build(project)
        assert self._id_of(result, "res://scripts/player.gd.Player.take_damage") in (
            result.reachable
        )

    def test_default_keeps_methods_alive(self, project):
        result = self._build(project)
        # method_dead_code defaults to False: only file/asset-level verdicts
        assert self._id_of(result, "res://scripts/player.gd.Player.never_called") in (
            result.reachable
        )

    def test_strict_mode_reports_the_uncalled_method(self, project):
        result = self._build(project, {"godot": {"method_dead_code": True}})
        dead = self._dead_qnames(result)
        assert "res://scripts/player.gd.Player.never_called" in dead
        assert "res://scripts/player.gd.Player.take_damage" not in dead
        assert "res://scripts/game_state.gd.add_score" in dead

    def test_orphan_script_and_scene_are_dead(self, project):
        result = self._build(project)
        dead = self._dead_qnames(result)
        assert "res://scripts/orphan.gd" in dead
        assert "res://scenes/orphan.tscn" in dead

    def test_main_scene_and_autoload_are_alive(self, project):
        result = self._build(project)
        reachable = result.reachable
        assert self._id_of(result, "res://scenes/level.tscn") in reachable
        assert self._id_of(result, "res://scripts/level.gd") in reachable
        assert self._id_of(result, "res://scripts/game_state.gd") in reachable

    def test_missing_resource_is_reported_with_file_and_line(self, project):
        result = self._build(project)
        broken = [
            w
            for w in result.warnings
            if w.warn_type == "unresolved_ref" and "ghost.gd" in w.message
        ]
        assert len(broken) == 1
        assert broken[0].file_path == "scenes/broken.tscn"
        assert broken[0].line == 3
        assert "res://scripts/ghost.gd" in broken[0].message

    def test_existing_paths_produce_no_unresolved_ref(self, project):
        result = self._build(project)
        problems = [
            w
            for w in result.warnings
            if w.warn_type == "unresolved_ref" and "ghost" not in w.message
        ]
        assert problems == []

    def test_no_syntax_or_import_warnings(self, project):
        result = self._build(project)
        for pr in result.files_data.values():
            kinds = {w.warn_type for w in pr.warnings}
            assert not (kinds & {"syntax_error", "unused_import"}), (pr.file_path, kinds)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
