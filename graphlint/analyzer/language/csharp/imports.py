# -*- coding: utf-8 -*-
"""C# import analyzer — resolves ``using`` directives."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class UseInfo:
    """Resolved ``using`` directive information."""

    module_path: str = ""
    imported_names: list[str] = field(default_factory=list)
    alias_map: dict[str, str] = field(default_factory=dict)
    is_static: bool = False
    line: int = 0


class CSharpImportAnalyzer:
    """Analyzes ``using``, ``using static``, and ``using alias`` directives."""

    def analyze_using(self, node: Any) -> "UseInfo | None":
        """Analyze a tree-sitter ``using_directive`` node.

        Handles:
            - ``using System;``                    → namespace import
            - ``using System.Collections.Generic;`` → qualified namespace
            - ``using static System.Math;``        → static import
            - ``using Timer = System.Timers.Timer;`` → alias
            - ``global using System;``              → global import (treated same)
        """
        module_path = ""
        imported_names: list[str] = []
        alias_map: dict[str, str] = {}
        is_static = False

        name_node = node.child_by_field_name("name")
        if not name_node:
            # Try to find qualified name or identifier among children
            for child in node.children:
                if child.type in ("qualified_name", "identifier"):
                    name_node = child
                    break

        if not name_node:
            return None

        module_path = _node_text(name_node)

        # Check for ``using static``
        for child in node.children:
            if child.type == "static":
                is_static = True
                break

        # Check for alias: ``using Foo = Bar;`` — the name field is the
        # right-hand side; the alias is a separate child.
        for child in node.children:
            if child.type == "name_equals":
                # Left of = is the alias name; right side is the actual type
                for c in child.children:
                    if c.type == "identifier":
                        imported_names.append(_node_text(c))
                break

        if is_static:
            # For static using, imported names are the static members
            imported_names.append("*")

        line = node.start_point[0] + 1 if hasattr(node, "start_point") and node.start_point else 0

        return UseInfo(
            module_path=module_path,
            imported_names=imported_names if imported_names else ["*"],
            alias_map=alias_map,
            is_static=is_static,
            line=line,
        )


def _node_text(node: Any) -> str:
    """Decode tree-sitter node text safely."""
    try:
        return node.text.decode("utf-8") if node.text else ""
    except (UnicodeDecodeError, AttributeError):
        return ""
