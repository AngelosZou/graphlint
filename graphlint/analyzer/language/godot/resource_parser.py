# -*- coding: utf-8 -*-
"""Hand-written ``.tscn`` / ``.tres`` parser.

Godot resource files are an ordered, INI-like text format::

    [gd_scene load_steps=2 format=3]
    [ext_resource type="Script" path="res://scripts/level.gd" id="1_k0juu"]
    [node name="World" type="Node2D"]
    script = ExtResource("1_k0juu")
    [connection signal="pressed" from="Button" to="." method="_on_pressed"]

Only the parts that carry a *dependency* matter here: ``ext_resource`` paths,
the ``ExtResource("id")``/``SubResource("id")`` references inside property
values, and ``[connection]`` declarations (which name a signal and a method on
the attached script).  Scene nodes themselves are deliberately not graph nodes:
a scene is one resource, and its elements are its data.
"""

from __future__ import annotations

import os
import re
from typing import Any, Iterator, Optional

from graphlint.analyzer._types import NodeInfo, ParseResult, ReferenceInfo

from .constants import (
    NODE_RESOURCE,
    NODE_SCENE,
    _file_to_module,
    _is_scene_file,
)
from .imports import GodotImportInfo, normalize_res_path

_ATTR_QUOTED_RE = re.compile(r'([A-Za-z_]\w*)\s*=\s*"([^"]*)"')
_ATTR_BARE_RE = re.compile(r"([A-Za-z_]\w*)\s*=\s*([^\s\]]+)")
_HEADER_NAME_RE = re.compile(r"^\[([A-Za-z_]\w*)")
_EXT_RES_RE = re.compile(r'ExtResource\(\s*"([^"]+)"\s*\)')
_SUB_RES_RE = re.compile(r'SubResource\(\s*"([^"]+)"\s*\)')

_EXT_RESOURCE = "ext_resource"
_SUB_RESOURCE = "sub_resource"


def iter_sections(text: str) -> Iterator[dict[str, Any]]:
    """Yield resource sections: ``{name, attrs, props, line}``.

    ``props`` is a list of ``(key, raw_value, line)``; a value that continues
    over several lines (``Object(…)`` blocks, wrapped ``PackedStringArray``) is
    accumulated by tracking bracket balance outside string literals.
    """
    lines = text.splitlines()
    index = 0
    section: Optional[dict[str, Any]] = None
    while index < len(lines):
        raw = lines[index]
        stripped = raw.strip()
        index += 1
        if not stripped or stripped.startswith(";"):
            continue
        if stripped.startswith("["):
            if section is not None:
                yield section
            name_match = _HEADER_NAME_RE.match(stripped)
            attrs: dict[str, str] = {}
            for match in _ATTR_QUOTED_RE.finditer(stripped):
                attrs[match.group(1)] = match.group(2)
            for match in _ATTR_BARE_RE.finditer(stripped):
                attrs.setdefault(match.group(1), match.group(2))
            section = {
                "name": name_match.group(1) if name_match else "",
                "attrs": attrs,
                "props": [],
                "line": index,
            }
            continue
        if section is None or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        line_no = index
        value = value.strip()
        balance = _bracket_balance(value)
        while balance > 0 and index < len(lines):
            continuation = lines[index]
            index += 1
            value += "\n" + continuation
            balance += _bracket_balance(continuation)
        section["props"].append((key.strip(), value, line_no))
    if section is not None:
        yield section


def _bracket_balance(text: str) -> int:
    depth = 0
    quote = ""
    escaped = False
    for char in text:
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
            continue
        if char in "\"'":
            quote = char
        elif char in "({[":
            depth += 1
        elif char in ")}]":
            depth -= 1
    return depth


def parse_resource(
    file_path: str,
    source: str,
    config: Optional[dict[str, Any]] = None,
) -> ParseResult:
    """Parse a ``.tscn`` / ``.tres`` file into graph material."""
    result = ParseResult(file_path=file_path)
    result.source = source
    qname = _file_to_module(file_path)
    node_type = NODE_SCENE if _is_scene_file(file_path) else NODE_RESOURCE

    result.nodes = [
        NodeInfo(
            file_id=0,
            name=_basename(file_path),
            qualified_name=qname,
            node_type=node_type,
            line_start=1,
            line_end=max(1, len(source.splitlines())),
            parent_node_id=0,
        )
    ]
    result.nodes[0].id = 1

    sections = list(iter_sections(source))

    # pass 1 — declared ids (references may appear before their declaration is
    # visible to a human reader, so resolve order-independently)
    ext_paths: dict[str, str] = {}
    sub_ids: set[str] = set()
    for section in sections:
        name = section["name"]
        if name == _EXT_RESOURCE:
            resource_id = section["attrs"].get("id", "")
            path = section["attrs"].get("path", "")
            if resource_id and path:
                ext_paths[resource_id] = path
        elif name == _SUB_RESOURCE:
            resource_id = section["attrs"].get("id", "")
            if resource_id:
                sub_ids.add(resource_id)

    references: list[ReferenceInfo] = []
    warnings: list[Any] = []
    imports: list[GodotImportInfo] = []
    dependency_paths: list[str] = []
    seen_paths: set[str] = set()

    # ext_resource declarations are the file's imports
    for section in sections:
        if section["name"] != _EXT_RESOURCE:
            continue
        path = section["attrs"].get("path", "")
        if not path.startswith("res://"):
            continue
        normalized = normalize_res_path(path)
        if normalized in seen_paths:
            continue
        seen_paths.add(normalized)
        dependency_paths.append(normalized)
        references.append(
            ReferenceInfo(
                source_qname=qname,
                target_name=normalized,
                edge_type="read",
                line=section["line"],
            )
        )
    for path in dependency_paths:
        imports.append(GodotImportInfo(path=path, line=0, kind="ext_resource"))

    scene_scripts: dict[str, str] = {}
    connections: list[dict[str, Any]] = []

    for section in sections:
        name = section["name"]
        if name == "node":
            node_path = _node_path(section["attrs"])
            for key, value, line in section["props"]:
                for match in _EXT_RES_RE.finditer(value):
                    resource_id = match.group(1)
                    if resource_id not in ext_paths:
                        warnings.append(
                            _warning(
                                "unresolved_ref",
                                f"ExtResource(\"{resource_id}\") is not declared in this scene",
                                file_path,
                                line,
                            )
                        )
                        continue
                    if key == "script":
                        scene_scripts[node_path] = ext_paths[resource_id]
                for match in _SUB_RES_RE.finditer(value):
                    if match.group(1) not in sub_ids:
                        warnings.append(
                            _warning(
                                "unresolved_ref",
                                f"SubResource(\"{match.group(1)}\") is not declared in this scene",
                                file_path,
                                line,
                            )
                        )
        elif name == "connection":
            connections.append(
                {
                    "from": section["attrs"].get("from", ""),
                    "to": section["attrs"].get("to", ""),
                    "signal": section["attrs"].get("signal", ""),
                    "method": section["attrs"].get("method", ""),
                    "line": section["line"],
                }
            )
        elif name == "resource":
            for key, value, line in section["props"]:
                for match in _EXT_RES_RE.finditer(value):
                    if match.group(1) not in ext_paths:
                        warnings.append(
                            _warning(
                                "unresolved_ref",
                                f"ExtResource(\"{match.group(1)}\") is not declared in this resource",
                                file_path,
                                line,
                            )
                        )

    result.references = references
    result.imports = imports
    result.warnings = warnings
    setattr(result, "godot_scene_scripts", scene_scripts)
    setattr(result, "godot_connections", connections)
    return result


def _node_path(attrs: dict[str, str]) -> str:
    name = attrs.get("name", "")
    parent = attrs.get("parent")
    if parent is None:
        return "."
    if parent in (".", ""):
        return name
    return f"{parent}/{name}"


def _basename(file_path: str) -> str:
    return os.path.basename(file_path.replace("\\", "/"))


def _warning(warn_type: str, message: str, file_path: str, line: int) -> Any:
    from graphlint.analyzer.warnings import WarningInfo

    return WarningInfo(
        warn_type=warn_type,
        severity="warning",
        message=message,
        file_path=file_path,
        line=line,
        node_id=0,
    )
