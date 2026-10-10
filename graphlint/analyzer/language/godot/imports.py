# -*- coding: utf-8 -*-
"""Godot resource dependencies (``preload`` / ``load`` / ``extends "res://…"``).

A GDScript "import" is a resource reference: the file depends on another
``res://`` resource.  The dataclass deliberately exposes no ``include_path``
attribute — the core's C/C++ include plumbing (``graph.py`` /
``incremental/_db_ops.py``) probes for that attribute with ``getattr`` and must
not treat Godot resources as C headers.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from typing import Any

#: A literal Godot resource path inside a string.
RES_PATH_RE = re.compile(r"^res://[^\s\"']+$")

#: Call names whose first string argument is a resource path.
RESOURCE_LOAD_CALLS: frozenset[str] = frozenset(
    {"preload", "load", "ResourceLoader.load", "ResourceLoader.load_threaded_request"}
)


@dataclass
class GodotImportInfo:
    """A single resource dependency declared in a GDScript file."""

    path: str = ""            # normalized ``res://…`` target
    line: int = 0
    kind: str = "preload"     # preload | load | extends | class_name
    name: str = ""            # bound constant/variable name, when there is one
    resolved: bool = True     # False when the path is computed at runtime


def is_res_path(value: str) -> bool:
    """True when *value* is a literal ``res://`` resource path."""
    return bool(value) and bool(RES_PATH_RE.match(value.strip()))


def normalize_res_path(value: str) -> str:
    """Normalize a ``res://`` path (collapse ``//``, drop a trailing slash)."""
    path = value.strip().strip('"').strip("'")
    path = path.replace("\\", "/")
    while "res://" in path.replace("res://", "", 1):
        path = path.replace("res://", "res://", 1)
    if not path.startswith("res://"):
        path = "res://" + path.lstrip("/")
    body = path[len("res://"):]
    body = re.sub(r"/{2,}", "/", body)
    return "res://" + body


def find_unused_resource_imports(
    imports: list[GodotImportInfo],
    name_usages: set[str],
    file_path: str,
) -> list[tuple[GodotImportInfo, str, int]]:
    """Return ``const X = preload(...)`` imports whose binding is never used.

    Only *named, preloaded* resources are checked: a bare ``load(path)`` call
    inside a function body is a use by construction, and a computed path is
    never reported (the ``godot`` adapter only reports what it can prove).
    """
    unused: list[tuple[GodotImportInfo, str, int]] = []
    for imp in imports:
        if not imp.name or not imp.resolved:
            continue
        if imp.kind not in ("preload", "load"):
            continue
        if imp.name in name_usages:
            continue
        unused.append(
            (
                imp,
                f"'{imp.name}' is preloaded but never used",
                imp.line,
            )
        )
    return unused


def matches_any(name: str, patterns: tuple[str, ...]) -> bool:
    """``fnmatch`` helper shared by the entry detector and the visitor."""
    return any(fnmatch.fnmatch(name, p) for p in patterns)


def config_section(config: dict[str, Any] | None) -> dict[str, Any]:
    """Return the ``godot`` config section (never ``None``)."""
    if not config:
        return {}
    section = config.get("godot")
    return section if isinstance(section, dict) else {}
