# -*- coding: utf-8 -*-
"""Godot source parser — dispatches to the ``.gd``, ``.tscn`` / ``.tres`` and
``project.godot`` parsers and exposes the module-level worker Graphlint's
process pool pickles."""

from __future__ import annotations

import os
from typing import Any, Optional

from graphlint.analyzer._types import ParseResult

from .constants import (
    _is_gd_file,
    _is_project_manifest,
    _is_resource_file,
    _is_scene_file,
)
from .gd_parser import parse_gd
from .project_parser import parse_project
from .resource_parser import parse_resource

_ENCODINGS = ("utf-8", "utf-8-sig", "latin-1")


class GodotSourceParser:
    """Parse one Godot file, choosing the parser from its format."""

    def __init__(self, root_dir: str, config: Optional[dict[str, Any]] = None) -> None:
        self.root_dir = root_dir
        self.config = config or {}

    def parse_file(self, full_path: str) -> ParseResult:
        file_path = os.path.relpath(full_path, self.root_dir).replace(os.sep, "/")
        source = _read_source(full_path)
        if source is None:
            result = ParseResult(file_path=file_path)
            result.warnings.append(
                _make_warning(
                    "syntax_error",
                    f"Could not read file: {file_path}",
                    file_path,
                    1,
                )
            )
            return result
        if _is_gd_file(file_path):
            return parse_gd(file_path, source, self.config)
        if _is_scene_file(file_path) or _is_resource_file(file_path):
            return parse_resource(file_path, source, self.config)
        if _is_project_manifest(file_path):
            return parse_project(file_path, source, self.config)
        result = ParseResult(file_path=file_path)
        result.source = source
        return result


def _read_source(path: str) -> Optional[str]:
    for encoding in _ENCODINGS:
        try:
            with open(path, "r", encoding=encoding) as handle:
                return handle.read()
        except (OSError, UnicodeDecodeError):
            continue
    return None


def _make_warning(
    warn_type: str, message: str, file_path: str, line: int
) -> Any:
    from graphlint.analyzer.warnings import WarningInfo

    return WarningInfo(
        warn_type=warn_type,
        severity="warning",
        message=message,
        file_path=file_path,
        line=line,
        node_id=0,
    )


def _parse_file_worker(
    full_path: str, root_dir: str, config: dict[str, Any]
) -> ParseResult:
    """Process-pool entry point (module level so it can be pickled)."""
    return GodotSourceParser(root_dir, config).parse_file(full_path)
