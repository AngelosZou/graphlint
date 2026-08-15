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
            - ``using A = B;``                    → alias to a same-namespace type
            - ``global using System;``              → global import (treated same)

        The alias form ``using Timer = System.Timers.Timer;`` parses in
        tree-sitter-c-sharp as: ``identifier(Timer)`` ``=``
        ``qualified_name(System.Timers.Timer)`` (the alias name also appears
        in the ``name`` field).  The real module path is the right-hand side
        (``System.Timers.Timer``), and the imported name is the alias
        (``Timer``).  A ``name_equals`` node **does not exist** in this
        grammar — detection must key on the ``=`` operator child.
        """
        children = list(node.children)
        is_static = any(c.type == "static" for c in children)
        has_equals = any(c.type == "=" for c in children)

        # --- alias using: ``using Timer = System.Timers.Timer;`` ---
        if has_equals:
            # Children are [identifier(alias), '=', target]; the target may
            # be a qualified_name / generic_name (``using A = X.Y;``) or a
            # plain identifier (``using A = B;`` — an alias of a type in the
            # current namespace).
            eq_idx = next(
                (i for i, c in enumerate(children) if c.type == "="), -1,
            )
            alias_name = ""
            for c in (children[:eq_idx] if eq_idx >= 0 else children):
                if c.type == "identifier":
                    alias_name = _node_text(c)
                    break
            module_path = ""
            for c in (children[eq_idx + 1:] if eq_idx >= 0 else []):
                if c.type in ("qualified_name", "generic_name", "identifier"):
                    module_path = _node_text(c)
                    break
            if not module_path or not alias_name:
                return None
            line = node.start_point[0] + 1 if hasattr(node, "start_point") and node.start_point else 0
            return UseInfo(
                module_path=module_path,
                imported_names=[alias_name],
                alias_map={alias_name: module_path},
                is_static=False,
                line=line,
            )

        # --- namespace importing : ``using System;`` / ``using static ...`` ---
        name_node = node.child_by_field_name("name")
        if not name_node:
            for c in children:
                if c.type in ("qualified_name", "identifier"):
                    name_node = c
                    break
        if not name_node:
            return None
        module_path = _node_text(name_node)
        line = node.start_point[0] + 1 if hasattr(node, "start_point") and node.start_point else 0
        return UseInfo(
            module_path=module_path,
            # Wildcard: single-file analysis cannot determine which types
            # from a namespace are referenced (or which static members).
            imported_names=["*"],
            alias_map={},
            is_static=is_static,
            line=line,
        )

    def detect_unused_imports(
        self,
        uses: list[UseInfo],
        name_usages: set[str],
        file_path: str = "",
    ) -> list[tuple[UseInfo, str, int]]:
        """Detect unused ``using`` directives.

        Wildcard imports (``using System;``, ``using static System.Math;``)
        are skipped because single-file analysis cannot determine whether
        types from the namespace are actually referenced.

        Alias imports (``using Timer = System.Timers.Timer;``) are checked
        against *name_usages*.

        .. note::
            Incremental rebuilds only parse changed files, so these warnings
            are produced for files parsed in the current build; unchanged
            files loaded from the index carry no import data.
        """
        unused: list[tuple[UseInfo, str, int]] = []
        for idx, use_info in enumerate(uses):
            if use_info.imported_names == ["*"]:
                continue
            used = any(n in name_usages for n in use_info.imported_names)
            if not used:
                names = ", ".join(use_info.imported_names)
                msg = (
                    f"Unused using directive: '{names}' "
                    f"(alias for '{use_info.module_path}')"
                )
                unused.append((use_info, msg, idx))
        return unused


def _node_text(node: Any) -> str:
    """Decode tree-sitter node text safely."""
    try:
        return node.text.decode("utf-8") if node.text else ""
    except (UnicodeDecodeError, AttributeError):
        return ""
