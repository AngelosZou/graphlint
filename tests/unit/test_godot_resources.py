# -*- coding: utf-8 -*-
"""Tests for the Godot resource parsers (.tscn / .tres / project.godot).

These formats are hand-written INI-like text, so the parser is hand-written too:
the tests pin the exact section/value accumulation rules and the references the
graph depends on.
"""

from __future__ import annotations

import pytest

from graphlint.analyzer.language.godot.constants import (
    NODE_PROJECT as GD_NODE_PROJECT,
    NODE_RESOURCE,
    NODE_SCENE,
)
from graphlint.analyzer.language.godot.project_parser import parse_project
from graphlint.analyzer.language.godot.resource_parser import (
    iter_sections,
    parse_resource,
)

SCENE = """[gd_scene load_steps=3 format=3]

[ext_resource type="Script" path="res://scripts/level.gd" id="1_k0juu"]
[ext_resource type="PackedScene" path="res://scenes/coin.tscn" id="2_71j4m"]

[sub_resource type="CircleShape2D" id="CircleShape2D_1"]
radius = 12.0

[node name="World" type="Node2D"]
script = ExtResource("1_k0juu")

[node name="Player" parent="." instance=ExtResource("2_71j4m")]

[node name="Sprite" parent="Player"]
texture = SubResource("CircleShape2D_1")

[connection signal="pressed" from="World/Button" to="World" method="_on_button_pressed"]
"""


class TestIterSections:
    def test_header_name_and_attrs(self):
        sections = list(iter_sections(SCENE))
        assert sections[0]["name"] == "gd_scene"
        # quoted and bare attributes both land in attrs
        assert sections[0]["attrs"]["format"] == "3"
        assert sections[0]["attrs"]["load_steps"] == "3"

    def test_ext_resource_attrs(self):
        ext = [s for s in iter_sections(SCENE) if s["name"] == "ext_resource"]
        assert ext[0]["attrs"] == {
            "type": "Script",
            "path": "res://scripts/level.gd",
            "id": "1_k0juu",
        }

    def test_header_line_numbers_are_one_based(self):
        sections = list(iter_sections(SCENE))
        # [gd_scene …] is line 1, the first ext_resource line 3
        assert sections[0]["line"] == 1
        assert sections[1]["line"] == 3

    def test_props_carry_key_value_and_line(self):
        node = [s for s in iter_sections(SCENE) if s["name"] == "node"][0]
        assert node["props"] == [("script", 'ExtResource("1_k0juu")', 10)]

    def test_comments_and_blank_lines_are_skipped(self):
        text = "; a comment\n\n[resource]\nvalue = 1\n"
        sections = list(iter_sections(text))
        assert len(sections) == 1
        assert sections[0]["name"] == "resource"
        assert sections[0]["props"] == [("value", "1", 4)]

    def test_multiline_value_is_accumulated_by_bracket_balance(self):
        text = (
            "[resource]\n"
            "items = PackedStringArray(\n"
            '"a",\n'
            '"b"\n'
            ")\n"
            "next = 1\n"
        )
        sections = list(iter_sections(text))
        props = sections[0]["props"]
        assert props[0][0] == "items"
        assert props[0][1].startswith("PackedStringArray(")
        assert props[0][1].endswith(")")
        assert props[0][2] == 2
        # the continuation lines were consumed, so the next prop keeps its line
        assert props[1] == ("next", "1", 6)

    def test_brackets_inside_strings_do_not_open_a_continuation(self):
        text = '[resource]\nname = "a[b"\nnext = 1\n'
        props = list(iter_sections(text))[0]["props"]
        assert props == [("name", '"a[b"', 2), ("next", "1", 3)]

    def test_value_with_equals_inside_string(self):
        text = '[ext_resource path="res://a=b.gd" id="1"]\n'
        section = list(iter_sections(text))[0]
        assert section["attrs"]["path"] == "res://a=b.gd"


class TestParseScene:
    def test_root_node(self):
        result = parse_resource("scenes/world.tscn", SCENE)
        assert len(result.nodes) == 1
        root = result.nodes[0]
        assert root.node_type == NODE_SCENE
        assert root.name == "world.tscn"
        assert root.qualified_name == "res://scenes/world.tscn"
        assert root.line_start == 1
        assert result.source == SCENE

    def test_ext_resource_paths_become_read_references(self):
        result = parse_resource("scenes/world.tscn", SCENE)
        targets = [r.target_name for r in result.references]
        assert targets == [
            "res://scripts/level.gd",
            "res://scenes/coin.tscn",
        ]
        assert all(r.edge_type == "read" for r in result.references)
        assert result.references[0].source_qname == "res://scenes/world.tscn"
        assert result.references[0].line == 3

    def test_ext_resource_paths_become_imports(self):
        result = parse_resource("scenes/world.tscn", SCENE)
        assert [(i.path, i.kind) for i in result.imports] == [
            ("res://scripts/level.gd", "ext_resource"),
            ("res://scenes/coin.tscn", "ext_resource"),
        ]

    def test_duplicate_ext_resource_path_is_reported_once(self):
        text = (
            '[gd_scene format=3]\n'
            '[ext_resource type="Script" path="res://a.gd" id="1"]\n'
            '[ext_resource type="Script" path="res://a.gd" id="2"]\n'
        )
        result = parse_resource("scenes/x.tscn", text)
        assert [r.target_name for r in result.references] == ["res://a.gd"]

    def test_scene_scripts_maps_node_path_to_script(self):
        result = parse_resource("scenes/world.tscn", SCENE)
        scripts = getattr(result, "godot_scene_scripts")
        # the root node has no parent attribute -> "."
        assert scripts == {".": "res://scripts/level.gd"}

    def test_node_paths_include_nested_parents(self):
        text = (
            '[gd_scene format=3]\n'
            '[ext_resource type="Script" path="res://a.gd" id="1"]\n'
            '[node name="Root" type="Node"]\n'
            'script = ExtResource("1")\n'
            '[node name="Child" parent="." type="Node"]\n'
            'script = ExtResource("1")\n'
            '[node name="Leaf" parent="Child" type="Node"]\n'
            'script = ExtResource("1")\n'
        )
        result = parse_resource("scenes/x.tscn", text)
        assert getattr(result, "godot_scene_scripts") == {
            ".": "res://a.gd",
            "Child": "res://a.gd",
            "Child/Leaf": "res://a.gd",
        }

    def test_connections_are_recorded(self):
        result = parse_resource("scenes/world.tscn", SCENE)
        conns = getattr(result, "godot_connections")
        assert len(conns) == 1
        assert conns[0]["signal"] == "pressed"
        assert conns[0]["method"] == "_on_button_pressed"
        assert conns[0]["from"] == "World/Button"
        assert conns[0]["to"] == "World"
        assert conns[0]["line"] == 17

    def test_undeclared_ext_resource_warns(self):
        text = (
            '[gd_scene format=3]\n'
            '[node name="Root" type="Node"]\n'
            'script = ExtResource("9_missing")\n'
        )
        result = parse_resource("scenes/x.tscn", text)
        assert [w.warn_type for w in result.warnings] == ["unresolved_ref"]
        assert "9_missing" in result.warnings[0].message
        assert result.warnings[0].line == 3
        assert result.warnings[0].file_path == "scenes/x.tscn"
        # an unknown id yields no script mapping and no reference
        assert getattr(result, "godot_scene_scripts") == {}

    def test_undeclared_sub_resource_warns(self):
        text = (
            '[gd_scene format=3]\n'
            '[node name="Root" type="Node"]\n'
            'shape = SubResource("9_missing")\n'
        )
        result = parse_resource("scenes/x.tscn", text)
        assert [w.warn_type for w in result.warnings] == ["unresolved_ref"]
        assert "SubResource" in result.warnings[0].message


class TestParseResource:
    def test_root_node_type_is_resource(self):
        text = (
            '[gd_resource type="Resource" script_class="GameData" format=3]\n'
            '[ext_resource type="Script" path="res://scripts/game_data.gd" id="1_x"]\n'
            "[resource]\n"
            'script = ExtResource("1_x")\n'
            'title = "hello"\n'
        )
        result = parse_resource("assets/level_data.tres", text)
        assert result.nodes[0].node_type == NODE_RESOURCE
        assert result.nodes[0].qualified_name == "res://assets/level_data.tres"
        assert [r.target_name for r in result.references] == [
            "res://scripts/game_data.gd"
        ]
        # a .tres records no scene scripts / connections
        assert getattr(result, "godot_scene_scripts") == {}
        assert getattr(result, "godot_connections") == []

    def test_undeclared_ext_resource_in_resource_section_warns(self):
        text = '[gd_resource type="Resource" format=3]\n[resource]\nscript = ExtResource("1_x")\n'
        result = parse_resource("assets/x.tres", text)
        assert [w.warn_type for w in result.warnings] == ["unresolved_ref"]
        assert "in this resource" in result.warnings[0].message


class TestParseProject:
    PROJECT = (
        "config_version=5\n"
        "\n"
        "[application]\n"
        "\n"
        'config/name="Demo"\n'
        'run/main_scene="res://scenes/level.tscn"\n'
        "\n"
        "[autoload]\n"
        "\n"
        'GameState="*res://scripts/game_state.gd"\n'
        'Disabled="res://scripts/old.gd"\n'
        "\n"
        "[display]\n"
        "\n"
        'window/size/viewport_width=640\n'
        "\n"
        "[internationalization]\n"
        "\n"
        'locale/translations=PackedStringArray("res://assets/main.en.translation")\n'
        "\n"
        "[editor_plugins]\n"
        "\n"
        'enabled=PackedStringArray("res://addons/demo/plugin.cfg")\n'
    )

    def test_root_node(self):
        result = parse_project("project.godot", self.PROJECT)
        assert len(result.nodes) == 1
        assert result.nodes[0].node_type == GD_NODE_PROJECT
        assert result.nodes[0].qualified_name == "res://project.godot"

    def test_res_paths_from_every_section_become_read_edges(self):
        result = parse_project("project.godot", self.PROJECT)
        targets = [r.target_name for r in result.references]
        assert targets == [
            "res://scenes/level.tscn",
            "res://scripts/game_state.gd",
            "res://scripts/old.gd",
            "res://assets/main.en.translation",
            "res://addons/demo/plugin.cfg",
        ]
        assert all(r.edge_type == "read" for r in result.references)
        assert all(i.kind == "project" for i in result.imports)
        # deduped: one reference and one import per distinct path
        assert len(result.references) == len(set(targets))
        assert len(result.imports) == 5

    def test_main_scene_and_line(self):
        result = parse_project("project.godot", self.PROJECT)
        assert getattr(result, "godot_project_main_scene") == "res://scenes/level.tscn"
        assert getattr(result, "godot_project_main_scene_line") == 6

    def test_autoloads_with_enabled_flag(self):
        result = parse_project("project.godot", self.PROJECT)
        autoloads = getattr(result, "godot_project_autoloads")
        assert autoloads["GameState"] == {
            "path": "res://scripts/game_state.gd",
            "line": 10,
            "enabled": True,
        }
        assert autoloads["Disabled"]["enabled"] is False

    def test_missing_main_scene_is_empty(self):
        result = parse_project("project.godot", "[application]\nconfig/name=\"x\"\n")
        assert getattr(result, "godot_project_main_scene") == ""
        assert getattr(result, "godot_project_main_scene_line") == 0
        assert getattr(result, "godot_project_autoloads") == {}

    def test_no_res_paths_at_all(self):
        result = parse_project("project.godot", "[display]\nwindow/size/viewport_width=640\n")
        assert result.references == []
        assert result.imports == []

    def test_uid_paths_are_not_references(self):
        result = parse_project(
            "project.godot",
            '[application]\nrun/main_scene="uid://abc123"\n',
        )
        assert result.references == []
        assert getattr(result, "godot_project_main_scene") == ""


def test_project_parser_module_has_no_dead_helper():
    """A leftover ``_os_basename`` helper was removed; keep it that way."""
    from graphlint.analyzer.language.godot import project_parser

    assert not hasattr(project_parser, "_os_basename")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
