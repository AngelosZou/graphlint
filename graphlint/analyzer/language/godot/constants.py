# -*- coding: utf-8 -*-
"""Godot-specific constants: availability flags, node-type mappings, engine
virtual names, excludes, path utilities.

One adapter owns every Godot resource extension (``.gd``, ``.tscn``, ``.tres``
and ``project.godot``) so that a Godot project is analysed as a single graph:
one resource path namespace, one entry surface (``project.godot`` declarations)
and one shared symbol table, exactly like the unified C/C++ adapter treats a
mixed C/C++ project.
"""

from __future__ import annotations

import fnmatch
import os
from typing import Any

# ---------------------------------------------------------------------------
# Tree-sitter availability
# ---------------------------------------------------------------------------

_TREE_SITTER_GDSCRIPT_AVAILABLE: bool = False
try:
    import tree_sitter  # noqa: F401
    import tree_sitter_gdscript  # noqa: F401

    _TREE_SITTER_GDSCRIPT_AVAILABLE = True
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Extensions
# ---------------------------------------------------------------------------

_GODOT_GD_EXTENSIONS: frozenset[str] = frozenset({".gd"})
_GODOT_RESOURCE_EXTENSIONS: frozenset[str] = frozenset({".tscn", ".tres"})
# ``.godot`` files are only interesting when they are ``project.godot`` (the
# project manifest); extension-based registration is the only hook the registry
# offers, so the parser filters by basename.
_GODOT_EXTENSIONS: frozenset[str] = (
    _GODOT_GD_EXTENSIONS | _GODOT_RESOURCE_EXTENSIONS | frozenset({".godot"})
)

_GODOT_PROJECT_FILE = "project.godot"

# ---------------------------------------------------------------------------
# Node types
# ---------------------------------------------------------------------------

NODE_SCRIPT = "script"
NODE_SCENE = "scene"
NODE_RESOURCE = "resource"
NODE_PROJECT = "project"
NODE_CLASS = "class"
NODE_FUNCTION = "function"
#: ``signal`` declarations reuse the core's ``event`` type **on purpose**: a
#: ``read`` edge only propagates through a target whose node type is listed in
#: ``_graph_algo._READ_PROMOTED_TYPES``, and that set contains ``event`` but
#: would not contain a Godot-specific ``signal``.  Naming it ``event`` is what
#: makes the owner→signal keep-alive edge actually mark the signal as live.
NODE_SIGNAL = "event"
#: ``const`` declarations reuse ``variable`` for the same class of reason: the
#: core promotes ``variable``/``field`` nodes that hang off a live root, and
#: ``warnings.detect_write_only_nodes`` reports a ``variable`` that nothing
#: reads as ``unused_variable`` — which is exactly the wanted verdict for an
#: unreferenced constant once ``godot.constant_dead_code`` is enabled.
NODE_CONSTANT = "variable"
NODE_ENUM = "enum"
NODE_ENUM_MEMBER = "enum_member"
NODE_VARIABLE = "variable"
NODE_FIELD = "field"

# ---------------------------------------------------------------------------
# Public API names — language-level names exempt from unused warnings
# ---------------------------------------------------------------------------

# Godot has no "public API by name" convention beyond ``_``-prefixed privacy;
# the escape hatches are configuration keys instead (see ``godot.*``).
_GODOT_PUBLIC_API_NAMES: frozenset[str] = frozenset()

# ---------------------------------------------------------------------------
# Special names — methods invoked implicitly by the engine
# ---------------------------------------------------------------------------
#
# Godot calls these virtual methods itself; they must never be reported as
# dead code even when nothing in the project references them.  The engine also
# promotes them from a reachable class to their siblings (``class_special_map``
# in the core), so a live script keeps its ``_ready``/``_process`` alive
# automatically once the script root node is reached.

_GODOT_ENGINE_VIRTUALS: frozenset[str] = frozenset(
    {
        # Object / RefCounted
        "_init", "_to_string", "_notification", "_get", "_set",
        "_get_property_list", "_property_can_revert", "_property_get_revert",
        "_validate_property", "_free", "_get_rid",
        # Node / Node2D / Node3D
        "_ready", "_enter_tree", "_exit_tree", "_process", "_physics_process",
        "_input", "_shortcut_input", "_unhandled_key_input", "_unhandled_input",
        "_input_event", "_get_configuration_warnings", "_process_priority",
        "_draw", "_integrate_forces",
        # Area / body callbacks
        "_body_entered", "_body_exited", "_body_shape_entered",
        "_body_shape_exited", "_area_entered", "_area_exited",
        "_area_shape_entered", "_area_shape_exited",
        # Control
        "_gui_input", "_get_minimum_size", "_get_tooltip", "_has_point",
        "_accessibility_get_contextual_info", "_structured_text_parser",
        "_get_drag_data", "_can_drop_data", "_drop_data", "_make_custom_tooltip",
        # Resource
        "_setup_local_to_scene", "_use_placeholder", "_get_import_options",
        # MainLoop
        "_initialize", "_finalize", "_begin_play",
        # EditorPlugin / EditorImportPlugin / EditorExportPlugin / EditorScript
        "_get_plugin_name", "_get_plugin_icon", "_get_state", "_set_state",
        "_has_main_screen", "_make_visible", "_get_breakpoints", "_handles",
        "_edit", "_get_window_layout", "_build", "_enable_plugin",
        "_disable_plugin", "_apply_changes", "_clear", "_save_external_data",
        "_get_unsaved_status", "_get_import_order", "_get_importer_name",
        "_get_option_visibility", "_get_preset_count", "_get_preset_name",
        "_get_recognized_extensions", "_get_resource_type", "_get_save_extension",
        "_get_visible_name", "_import", "_export_file", "_export_begin",
        "_export_end", "_get_export_options", "_get_name", "_get_customization",
        "_run", "_get_base_class", "_get_default_extension",
        # GDExtension / ScriptExtension
        "_get_property_default_value", "_has_script_signal", "_get_script_method",
        "_get_documentation", "_get_class_icon", "_get_global_name",
        "_is_tool", "_is_valid", "_inherits_script", "_can_instantiate",
        "_instance_create", "_get_language",
    }
)

#: Name prefixes that mark an implicitly-wired method.  ``_on_*`` is the
#: editor's own convention for signal handlers created by "Connect…", so those
#: are exempt from dead-code reporting even when the connection lives outside
#: the analysed project.
_GODOT_SPECIAL_NAME_PREFIXES: tuple[str, ...] = ("_on_",)

_GODOT_SPECIAL_NAMES: frozenset[str] = _GODOT_ENGINE_VIRTUALS

# ---------------------------------------------------------------------------
# Default excludes
# ---------------------------------------------------------------------------

#: Godot-specific directories to skip.
#:
#: Deliberately EMPTY, although one would expect ``.godot``/``.import``/
#: ``addons/gut`` here:
#:
#: * ``.godot``, ``.import`` and ``.mono`` are dot-directories, and
#:   ``LanguageRegistry.scan_files`` already prunes every directory starting
#:   with ``.`` (registry.py:229) — listing them changes nothing.
#: * Export output directories (``bin``/``export``) are user-configurable and
#:   often contain hand-written code; excluding them by name would hide real
#:   source.
#: * The registry's excludes are **basename** matches and are UNIONED across
#:   every registered adapter (``all_default_excludes``), so a name listed here
#:   would also silently prune that directory in Python/Rust/C++ projects
#:   analysed in the same session.  A path-scoped pattern such as
#:   ``addons/gut`` cannot be expressed at all by that mechanism.
#:
#: Projects that want extra directories skipped add them through
#: ``exclude_patterns.user_exclude`` in ``.graphlint/config.json``.
_GODOT_DEFAULT_EXCLUDES: frozenset[str] = frozenset()

# ---------------------------------------------------------------------------
# Test file detection
# ---------------------------------------------------------------------------

_GODOT_TEST_FILE_PATTERNS: tuple[str, ...] = (
    "test_*.gd",
    "*_test.gd",
    "test_*.tscn",
)

#: Directories that hold Godot tests (GUT / gdUnit4 / WAT).
_GODOT_TEST_DIR_PATTERNS: tuple[str, ...] = (
    "test/",
    "tests/",
    "test/unit/",
    "test/integration/",
    "spec/",
)


def _is_test_file(file_path: str, config: dict[str, Any]) -> bool:
    """Check whether *file_path* is a Godot test script/scene."""
    test_patterns = config.get("test_patterns", {}) if config else {}
    file_patterns = test_patterns.get("file_patterns", list(_GODOT_TEST_FILE_PATTERNS))
    dir_patterns = test_patterns.get("dir_patterns", list(_GODOT_TEST_DIR_PATTERNS))

    normalized = file_path.replace("\\", "/")
    basename = os.path.basename(normalized)

    for pattern in _GODOT_TEST_FILE_PATTERNS:
        if fnmatch.fnmatch(basename, pattern):
            return True

    segments = [s for s in normalized.split("/") if s][:-1]
    for d in _GODOT_TEST_DIR_PATTERNS:
        d_clean = d.rstrip("/")
        if d_clean and d_clean in segments:
            return True
    for d in dir_patterns:
        d_clean = str(d).rstrip("/")
        if d_clean and d_clean in segments:
            return True

    for pattern in file_patterns:
        if fnmatch.fnmatch(basename, str(pattern)):
            return True

    return False


# ---------------------------------------------------------------------------
# Path utilities
# ---------------------------------------------------------------------------

_RES_PREFIX = "res://"


def _file_to_module(path: str) -> str:
    """Convert a project-relative path to its Godot resource path.

    >>> _file_to_module("scripts/player.gd")
    'res://scripts/player.gd'

    The resource path is the identity of every Godot file in the graph: it is
    what ``preload``/``load``/``ext_resource``/``main_scene``/autoload values
    contain, and it is used as the qualified name of the file's root node so
    that a path reference resolves through the exact symbol index.
    """
    normalized = path.replace("\\", "/").strip()
    if normalized.startswith(_RES_PREFIX):
        return normalized
    normalized = normalized.lstrip("/")
    return _RES_PREFIX + normalized


def _to_res_path(path: str) -> str:
    """Normalize *path* to a ``res://`` resource path (see :func:`_file_to_module`)."""
    return _file_to_module(path)


def _is_project_manifest(file_path: str) -> bool:
    """True when *file_path* is the project manifest (``project.godot``)."""
    return os.path.basename(file_path.replace("\\", "/")) == _GODOT_PROJECT_FILE


def _is_gd_file(file_path: str) -> bool:
    return file_path.lower().endswith(".gd")


def _is_scene_file(file_path: str) -> bool:
    return file_path.lower().endswith(".tscn")


def _is_resource_file(file_path: str) -> bool:
    return file_path.lower().endswith(".tres")


def _is_godot_file(file_path: str) -> bool:
    """True for any file this adapter owns (``.gd``, ``.tscn``, ``.tres``,
    ``project.godot``)."""
    return (
        _is_gd_file(file_path)
        or _is_scene_file(file_path)
        or _is_resource_file(file_path)
        or _is_project_manifest(file_path)
    )


# ---------------------------------------------------------------------------
# Tree-sitter Language singleton (lazy, per-process)
# ---------------------------------------------------------------------------

_GD_LANG: Any = None


def _get_gdscript_language() -> Any:
    """Return the tree-sitter Language for GDScript."""
    global _GD_LANG
    if _GD_LANG is None:
        if not _TREE_SITTER_GDSCRIPT_AVAILABLE:
            raise ImportError(
                "tree-sitter-gdscript is not installed. "
                "Install with: pip install graphlint[godot]"
            )
        import tree_sitter
        import tree_sitter_gdscript

        _GD_LANG = tree_sitter.Language(tree_sitter_gdscript.language())
    return _GD_LANG
