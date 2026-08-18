# -*- coding: utf-8 -*-
"""C import analyzer — resolves ``#include`` directives."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CIncludeInfo:
    """Resolved ``#include`` directive information."""

    include_path: str = ""
    is_system: bool = False
    line: int = 0


class CImportAnalyzer:
    """Analyzes ``#include`` preprocessor directives.

    Only local includes (``"foo.h"`` via ``string_literal``) are recorded as
    tracked file dependencies.  System includes (``<stdio.h>`` via
    ``system_lib_string``) are conservatively skipped — the same approach the
    C# backend takes for ``using System.*``.
    """

    def analyze_include(self, node: Any) -> CIncludeInfo | None:
        """Analyze a tree-sitter ``preproc_include`` node.

        Returns ``CIncludeInfo`` for local includes, ``None`` for system
        includes (which are ignored), or ``None`` if the node is
        unparseable.
        """
        include_path = ""
        is_system = False

        for child in node.children:
            if child.type == "system_lib_string":
                is_system = True
                include_path = _node_text(child)
                break
            elif child.type == "string_literal":
                include_path = _node_text(child)
                break

        if not include_path:
            return None

        if is_system:
            return None

        path = include_path.strip('"').strip("'")
        if not path:
            return None

        line = (
            node.start_point[0] + 1
            if hasattr(node, "start_point") and node.start_point
            else 0
        )

        return CIncludeInfo(
            include_path=path,
            is_system=False,
            line=line,
        )


def _node_text(node: Any) -> str:
    """Decode tree-sitter node text safely."""
    try:
        return node.text.decode("utf-8") if node.text else ""
    except (UnicodeDecodeError, AttributeError):
        return ""
