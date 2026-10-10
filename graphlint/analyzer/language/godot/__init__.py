# -*- coding: utf-8 -*-
"""Godot adapter — GDScript scripts plus the project's resource files.

Unlike every other adapter this one owns several *file formats* rather than a
single language:

* ``.gd``      — GDScript, parsed with ``tree-sitter-gdscript``
* ``.tscn``    — scenes (what attaches scripts to nodes)
* ``.tres``    — custom resources
* ``project.godot`` — the project manifest (main scene, autoloads, settings)

Keeping the four in one adapter is what lets the graph answer Godot-specific
questions: a scene ``read``s the scripts it attaches, the manifest ``read``s
the main scene and the autoloads, and a script ``read``s whatever it
``preload``s or ``load``s — all inside one resource-path namespace, so
reachability and dead-code analysis need no per-format special case.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from graphlint.analyzer._types import EntryInfo, NodeInfo, ParseResult
from graphlint.analyzer.language.base import LanguageAdapter

from .checks import validate_godot_graph
from .constants import (
    _GODOT_DEFAULT_EXCLUDES,
    _GODOT_EXTENSIONS,
    _GODOT_GD_EXTENSIONS,
    _GODOT_PUBLIC_API_NAMES,
    _GODOT_SPECIAL_NAMES,
    _GODOT_SPECIAL_NAME_PREFIXES,
    _file_to_module,
    _is_test_file,
)
from .entry import GdEntryPointDetector
from .parser import GodotSourceParser, _parse_file_worker

#: Extensions that need no tree-sitter grammar at all: the scene / resource /
#: manifest parsers are hand-written, so they keep working when
#: ``tree-sitter-gdscript`` is not installed.
_GRAMMAR_FREE_EXTENSIONS: frozenset[str] = (
    _GODOT_EXTENSIONS - _GODOT_GD_EXTENSIONS
)


class GodotAdapter(LanguageAdapter):
    """Language adapter for Godot 4 projects."""

    language_name = "godot"
    file_extensions = frozenset(_GODOT_EXTENSIONS)

    def __init__(self, extensions: Optional[frozenset[str]] = None) -> None:
        if extensions is not None:
            self.file_extensions = frozenset(extensions)

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    @property
    def worker_function(self) -> Callable[..., ParseResult]:
        return _parse_file_worker

    def parse_file(
        self, full_path: str, root_dir: str, config: dict[str, Any]
    ) -> ParseResult:
        parser = GodotSourceParser(root_dir, config)
        return parser.parse_file(full_path)

    # ------------------------------------------------------------------
    # Entries
    # ------------------------------------------------------------------

    def detect_entries(
        self,
        parse_results: dict[str, ParseResult],
        nodes: list[NodeInfo],
        node_id_map: dict[int, NodeInfo],
        config: dict[str, Any],
    ) -> list[Any]:
        detector = GdEntryPointDetector(config)
        return detector.detect(parse_results, nodes, node_id_map)

    # ------------------------------------------------------------------
    # Naming / classification
    # ------------------------------------------------------------------

    def file_to_module(self, path: str) -> str:
        return _file_to_module(path)

    def is_test_file(self, file_path: str, config: dict[str, Any]) -> bool:
        return _is_test_file(file_path, config)

    @property
    def public_api_names(self) -> frozenset[str]:
        # Godot has no name-level public API convention; ``class_name``
        # scripts are kept alive through a detected entry (see entry.py).
        return _GODOT_PUBLIC_API_NAMES

    @property
    def special_names(self) -> frozenset[str]:
        return _GODOT_SPECIAL_NAMES

    def is_special_name(self, name: str) -> bool:
        """Engine virtuals and editor-generated signal handlers.

        A special name is never reported as dead code and is promoted together
        with its owner, because the engine calls it implicitly.
        """
        if name in _GODOT_SPECIAL_NAMES:
            return True
        return name.startswith(_GODOT_SPECIAL_NAME_PREFIXES)

    @property
    def default_excludes(self) -> frozenset[str]:
        return _GODOT_DEFAULT_EXCLUDES

    # ------------------------------------------------------------------
    # Cross-file validation
    # ------------------------------------------------------------------

    def validate_graph(
        self,
        parse_results: dict[str, ParseResult],
        nodes: list[NodeInfo],
        node_id_map: dict[int, NodeInfo],
        edges: list[Any],
        file_id_map: dict[str, int],
        root_dir: Optional[str],
        config: dict[str, Any],
    ) -> list[Any]:
        """Checks that need the whole project (see :mod:`.checks`)."""
        return validate_godot_graph(
            parse_results,
            nodes,
            node_id_map,
            edges,
            file_id_map,
            root_dir,
            config,
        )


def build_adapter() -> LanguageAdapter:
    """Return the adapter with the best extension set for this install.

    Without ``tree-sitter-gdscript`` the GDScript half cannot be parsed, but
    scenes, resources and the manifest still can — so a partial adapter is
    registered rather than none, and :func:`graphlint.api._warn_missing_lang_support`
    tells the user how to enable the rest.
    """
    from .constants import _TREE_SITTER_GDSCRIPT_AVAILABLE

    if _TREE_SITTER_GDSCRIPT_AVAILABLE:
        return GodotAdapter()
    return GodotAdapter(extensions=_GRAMMAR_FREE_EXTENSIONS)


__all__ = ["GodotAdapter", "build_adapter"]
