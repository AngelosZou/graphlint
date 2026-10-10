# -*- coding: utf-8 -*-
"""``project.godot`` parser.

The project manifest is the root of a Godot project's dependency graph: the
main scene, every enabled autoload singleton, the default bus layout, custom
themes, translations and boot splash are all ``res://`` paths declared here.
Every ``res://`` string in a value becomes a ``read`` edge from the project
root, so the manifest acts as the entry point that keeps the real entry
surfaces alive.

Values are scanned rather than interpreted: Godot stores nested
``Object(InputEventKey,…)`` literals and multi-line ``PackedStringArray(…)``
values in the same INI-like format, and the section iterator merges those into
one value before the paths are extracted.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from graphlint.analyzer._types import NodeInfo, ParseResult, ReferenceInfo

from .constants import NODE_PROJECT, _file_to_module
from .imports import GodotImportInfo, normalize_res_path
from .resource_parser import iter_sections

_RES_PATH_IN_VALUE_RE = re.compile(r'res://[^"\s\)\],]+')

_AUTOLOAD_ENABLED_MARK = "*"


def parse_project(
    file_path: str,
    source: str,
    config: Optional[dict[str, Any]] = None,
) -> ParseResult:
    """Parse ``project.godot`` into graph material."""
    result = ParseResult(file_path=file_path)
    result.source = source
    qname = _file_to_module(file_path)

    result.nodes = [
        NodeInfo(
            file_id=0,
            name="project.godot",
            qualified_name=qname,
            node_type=NODE_PROJECT,
            line_start=1,
            line_end=max(1, len(source.splitlines())),
            parent_node_id=0,
        )
    ]
    result.nodes[0].id = 1

    references: list[ReferenceInfo] = []
    imports: list[GodotImportInfo] = []
    seen_paths: set[str] = set()
    main_scene = ""
    main_scene_line = 0
    autoloads: dict[str, dict[str, Any]] = {}

    for section in iter_sections(source):
        section_name = section["name"]
        for key, value, line in section["props"]:
            paths = [normalize_res_path(p) for p in _RES_PATH_IN_VALUE_RE.findall(value)]
            for path in paths:
                if path not in seen_paths:
                    seen_paths.add(path)
                    references.append(
                        ReferenceInfo(
                            source_qname=qname,
                            target_name=path,
                            edge_type="read",
                            line=line,
                        )
                    )
                    imports.append(
                        GodotImportInfo(path=path, line=line, kind="project")
                    )
            if section_name == "application" and key == "run/main_scene" and paths:
                main_scene = paths[0]
                main_scene_line = line
            elif section_name == "autoload" and paths:
                enabled = _AUTOLOAD_ENABLED_MARK in value
                autoloads[key] = {
                    "path": paths[0],
                    "line": line,
                    "enabled": enabled,
                }

    result.references = references
    result.imports = imports
    setattr(result, "godot_project_main_scene", main_scene)
    setattr(result, "godot_project_main_scene_line", main_scene_line)
    setattr(result, "godot_project_autoloads", autoloads)
    return result
