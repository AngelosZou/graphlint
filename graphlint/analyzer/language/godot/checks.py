# -*- coding: utf-8 -*-
"""Cross-file validation for Godot projects (the ``validate_graph`` hook).

A single-file visitor cannot decide these: they compare what the code *says*
against what the project *contains*.  Every check here follows the adapter's
"only confident verdicts" rule:

* a path-shaped literal that is missing is reported (``res://scenes/x.tscn``),
  an identifier that is merely unknown is not;
* anything the project can legitimately generate at runtime is skipped
  (``res://.godot/…``, ``uid://`` references, glob patterns, directories);
* ``godot.assume_assets_reachable: true`` turns every asset-existence check
  off for projects that build their resources at runtime.

Warn types are reused from the core whitelist on purpose (``unresolved_ref``,
``circular_ref``) so no new warning kind — and no coordinated i18n/params edit
— is introduced.
"""

from __future__ import annotations

import os
from typing import Any, Optional

from graphlint.analyzer._types import NodeInfo, ParseResult

from .constants import (
    _is_gd_file,
    _is_godot_file,
    _is_project_manifest,
)
from .imports import config_section

#: Suffixes a ``res://`` literal may carry and still be checked on disk.
_CHECKED_SUFFIXES: frozenset[str] = frozenset(
    {
        ".gd",
        ".tscn",
        ".tres",
        ".res",
        ".gdshader",
        ".shader",
        ".theme",
        ".json",
        ".cfg",
        ".import",
        ".translation",
        ".po",
        ".csv",
        ".png",
        ".jpg",
        ".jpeg",
        ".svg",
        ".webp",
        ".bmp",
        ".wav",
        ".ogg",
        ".mp3",
        ".ttf",
        ".otf",
    }
)

#: Never checked: generated trees and non-file references.
_SKIP_PREFIXES: tuple[str, ...] = ("res://.godot/", "res://.import/", "uid://")

_MAX_CYCLES = 20


def validate_godot_graph(
    parse_results: dict[str, ParseResult],
    nodes: list[NodeInfo],
    node_id_map: dict[int, NodeInfo],
    edges: list[Any],
    file_id_map: dict[str, int],
    root_dir: Optional[str],
    config: dict[str, Any],
) -> list[Any]:
    """Run every cross-file Godot check and return the warnings it proves."""
    if not root_dir:
        return []

    godot_files = {
        fp: pr for fp, pr in parse_results.items() if _is_godot_file(fp)
    }
    if not godot_files:
        return []

    qname_to_id = {n.qualified_name: n.id for n in nodes}
    settings = config_section(config)
    check_assets = not settings.get("assume_assets_reachable", False)

    warnings: list[Any] = []
    if check_assets:
        warnings.extend(
            _check_resource_paths(godot_files, root_dir, qname_to_id)
        )
        warnings.extend(_check_project_manifest(godot_files, root_dir))
    warnings.extend(_check_duplicate_class_names(godot_files))
    warnings.extend(_check_resource_cycles(godot_files))
    return warnings


# ----------------------------------------------------------------------
# P0: every referenced resource exists
# ----------------------------------------------------------------------


def _check_resource_paths(
    godot_files: dict[str, ParseResult],
    root_dir: str,
    qname_to_id: dict[str, int],
) -> list[Any]:
    """``res://`` literals in scripts, scenes and resources must exist."""
    warnings: list[Any] = []
    reported: set[tuple[str, str]] = set()

    for file_path, pr in godot_files.items():
        for ref in getattr(pr, "references", None) or ():
            raw = getattr(ref, "target_name", "") or ""
            if not raw.startswith("res://") or not _is_checkable_path(raw):
                continue
            if _res_path_exists(raw, root_dir):
                continue
            key = (file_path, raw)
            if key in reported:
                continue
            reported.add(key)
            warnings.append(
                _warn(
                    "unresolved_ref",
                    f"Referenced resource does not exist: {raw}",
                    file_path,
                    getattr(ref, "line", 0) or 0,
                    qname_to_id.get(getattr(ref, "source_qname", ""), 0),
                )
            )
    return warnings


def _check_project_manifest(
    godot_files: dict[str, ParseResult],
    root_dir: str,
) -> list[Any]:
    """``run/main_scene`` and every autoload must exist (and be the right type)."""
    warnings: list[Any] = []

    for file_path, pr in godot_files.items():
        if not _is_project_manifest(file_path):
            continue

        main_scene = getattr(pr, "godot_project_main_scene", "") or ""
        if main_scene:
            line = getattr(pr, "godot_project_main_scene_line", 0) or 0
            if not _res_path_exists(main_scene, root_dir):
                warnings.append(
                    _warn(
                        "unresolved_ref",
                        f"[application] run/main_scene does not exist: {main_scene}",
                        file_path,
                        line,
                    )
                )
            elif not main_scene.endswith(".tscn"):
                warnings.append(
                    _warn(
                        "unresolved_ref",
                        f"[application] run/main_scene is not a scene: {main_scene}",
                        file_path,
                        line,
                    )
                )

        autoloads = getattr(pr, "godot_project_autoloads", None) or {}
        for name, info in sorted(autoloads.items()):
            if not isinstance(info, dict):
                continue
            path = str(info.get("path", "") or "")
            line = int(info.get("line", 0) or 0)
            if not path.startswith("res://"):
                continue
            if not _res_path_exists(path, root_dir):
                warnings.append(
                    _warn(
                        "unresolved_ref",
                        f"Autoload '{name}' points at a missing script: {path}",
                        file_path,
                        line,
                    )
                )
            elif not path.endswith(".gd"):
                warnings.append(
                    _warn(
                        "unresolved_ref",
                        f"Autoload '{name}' is not a GDScript file: {path}",
                        file_path,
                        line,
                    )
                )
    return warnings


# ----------------------------------------------------------------------
# P1: repo-level consistency
# ----------------------------------------------------------------------


def _check_duplicate_class_names(
    godot_files: dict[str, ParseResult],
) -> list[Any]:
    """``class_name`` is a project-wide registry: duplicates are ambiguous."""
    declared: dict[str, list[tuple[str, int]]] = {}
    for file_path, pr in godot_files.items():
        if not _is_gd_file(file_path):
            continue
        name = getattr(pr, "godot_class_name", "") or ""
        if not name:
            continue
        line = 1
        owner = getattr(pr, "godot_owner_qname", "") or ""
        for node in pr.nodes:
            if node.qualified_name == owner:
                line = node.line_start
                break
        declared.setdefault(name, []).append((file_path, line))

    warnings: list[Any] = []
    for name, holders in sorted(declared.items()):
        if len(holders) < 2:
            continue
        others = ", ".join(f"{fp}:{line}" for fp, line in holders[1:])
        for file_path, line in holders[:1]:
            warnings.append(
                _warn(
                    "unresolved_ref",
                    f"Duplicate class_name '{name}' — also declared at {others}",
                    file_path,
                    line,
                )
            )
    return warnings


def _check_resource_cycles(godot_files: dict[str, ParseResult]) -> list[Any]:
    """Scenes/scripts/resources that reference each other in a cycle.

    The core only detects cycles over ``call``/``inherit`` edges, and a Godot
    resource cycle is a ``read`` edge, so it is reported explicitly here.
    """
    known = set(godot_files)
    adjacency: dict[str, list[str]] = {}
    lines: dict[tuple[str, str], int] = {}

    for file_path, pr in godot_files.items():
        out: list[str] = []
        for ref in getattr(pr, "references", None) or ():
            raw = getattr(ref, "target_name", "") or ""
            if not raw.startswith("res://"):
                continue
            target = _res_path_to_rel(raw)
            if target not in known or target == file_path:
                continue
            if target not in out:
                out.append(target)
                lines.setdefault((file_path, target), getattr(ref, "line", 0) or 0)
        adjacency[file_path] = out

    warnings: list[Any] = []
    for cycle in _find_cycles(adjacency)[:_MAX_CYCLES]:
        head = cycle[0]
        target = cycle[-1]
        warnings.append(
            _warn(
                "circular_ref",
                "Resource dependency cycle: " + " -> ".join(cycle + [head]),
                head,
                lines.get((head, target), 0),
            )
        )
    return warnings


def _find_cycles(adjacency: dict[str, list[str]]) -> list[list[str]]:
    """Iterative DFS returning each simple cycle once (order-independent)."""
    white, grey, black = 0, 1, 2
    color: dict[str, int] = {node: white for node in adjacency}
    cycles: list[list[str]] = []
    seen: set[frozenset[str]] = set()

    for start in adjacency:
        if color[start] != white:
            continue
        color[start] = grey
        path = [start]
        stack: list[tuple[str, Any]] = [(start, iter(adjacency.get(start, ())))]
        while stack:
            node, iterator = stack[-1]
            advanced = False
            for nxt in iterator:
                if nxt not in color:
                    continue
                state = color[nxt]
                if state == grey:
                    if nxt in path:
                        index = path.index(nxt)
                        cycle = path[index:]
                        key = frozenset(cycle)
                        if key not in seen:
                            seen.add(key)
                            cycles.append(list(cycle))
                    continue
                if state == white:
                    color[nxt] = grey
                    path.append(nxt)
                    stack.append((nxt, iter(adjacency.get(nxt, ()))))
                    advanced = True
                    break
            if not advanced:
                color[node] = black
                path.pop()
                stack.pop()
    return cycles


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------


def _warn(
    warn_type: str,
    message: str,
    file_path: str,
    line: int = 0,
    node_id: int = 0,
) -> Any:
    from graphlint.analyzer.warnings import WarningInfo

    severity = "info" if warn_type == "dynamic_import" else "warning"
    return WarningInfo(
        warn_type=warn_type,
        severity=severity,
        message=message,
        file_path=file_path,
        line=line,
        node_id=node_id,
    )


def _is_checkable_path(path: str) -> bool:
    """True for a concrete file path this adapter may verify on disk."""
    if path.endswith("/") or "*" in path or "?" in path:
        return False
    if any(path.startswith(prefix) for prefix in _SKIP_PREFIXES):
        return False
    suffix = os.path.splitext(path.split("?")[0])[1].lower()
    return suffix in _CHECKED_SUFFIXES


def _res_path_to_rel(path: str) -> str:
    return path[len("res://") :]


def _res_path_exists(path: str, root_dir: str) -> bool:
    rel = _res_path_to_rel(path)
    if not rel:
        return True
    candidate = os.path.join(root_dir, rel.replace("/", os.sep))
    return os.path.exists(candidate)


__all__ = ["validate_godot_graph"]
