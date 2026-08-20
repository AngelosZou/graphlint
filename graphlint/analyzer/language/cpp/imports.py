# -*- coding: utf-8 -*-
"""C++ import analyzer — resolves ``#include`` directives."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class IncludeInfo:
    """Resolved ``#include`` directive information."""

    include_path: str = ""
    is_system: bool = False
    line: int = 0


class CppImportAnalyzer:
    """Analyzes ``#include`` directives.

    System includes (``<...>``) are skipped; local includes (``"..."``)
    are recorded.
    """

    def analyze_include(self, node: Any) -> IncludeInfo | None:
        path_node = node.child_by_field_name("path")
        if not path_node:
            return None

        path_text = _node_text(path_node)
        if not path_text:
            return None

        # Strip surrounding quotes from local includes (#include "...")
        if path_node.type == "string_literal":
            path_text = path_text.strip('"')

        is_system = path_node.type == "system_lib_string"

        line = (
            node.start_point[0] + 1
            if hasattr(node, "start_point") and node.start_point
            else 0
        )

        return IncludeInfo(
            include_path=path_text,
            is_system=is_system,
            line=line,
        )


def _node_text(node: Any) -> str:
    """Decode tree-sitter node text safely."""
    try:
        return node.text.decode("utf-8") if node.text else ""
    except (UnicodeDecodeError, AttributeError):
        return ""
