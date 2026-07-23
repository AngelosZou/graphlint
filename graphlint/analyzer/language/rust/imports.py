# -*- coding: utf-8 -*-
"""Rust `use` statement analysis — extracts and analyzes import declarations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional, Set


@dataclass
class UseInfo:
    """Information about a single `use` declaration."""

    line: int = 0
    full_path: str = ""
    imported_names: List[str] = field(default_factory=list)
    is_used: bool = False
    used_at_lines: List[int] = field(default_factory=list)
    alias_map: dict[str, str] = field(default_factory=dict)  # imported_name → aliased_name


class RustImportAnalyzer:
    """Analyzes `use` declarations in Rust source files.

    Extracts the imported module path and the list of imported names
    from tree-sitter ``use_declaration`` nodes.
    """

    def __init__(self) -> None:
        self._usages: dict[str, Set[str]] = {}

    def analyze_use(self, node: Any, file_path: str = "") -> Optional[UseInfo]:
        """Extract import information from a tree-sitter ``use_declaration`` node.

        Args:
            node: A tree-sitter Node of type ``use_declaration``.
            file_path: Source file path (for diagnostics).

        Returns:
            A :class:`UseInfo`, or ``None`` if the node could not be analyzed.
        """
        if node.type != "use_declaration":
            return None

        import_path = ""
        imported_names: list[str] = []
        alias_map: dict[str, str] = {}
        line = node.start_point[0] + 1 if node.start_point else 0

        self._collect_use_path_and_names(node, "", imported_names, alias_map)
        import_path = self._build_use_path(node)

        if not imported_names and not import_path:
            return None

        # If no explicit names were extracted (e.g., `use std::fs;`),
        # the last segment of the path is the imported name.
        if not imported_names and import_path:
            imported_names.append(import_path.split("::")[-1])

        return UseInfo(
            line=line,
            full_path=import_path,
            imported_names=imported_names,
            alias_map=alias_map,
        )

    def detect_unused_imports(
        self,
        uses: list[UseInfo],
        name_usages: set[str],
        file_path: str = "",
    ) -> list[tuple[UseInfo, str, int]]:
        """Detect unused `use` declarations.

        Args:
            uses: List of :class:`UseInfo` from ``analyze_use``.
            name_usages: Set of simple names referenced in the file.
            file_path: Source file path (for messages).

        Returns:
            List of ``(UseInfo, message_string, unused_index)`` tuples.
        """
        unused: list[tuple[UseInfo, str, int]] = []
        for idx, use_info in enumerate(uses):
            if use_info.is_used:
                continue
            resolved_names = [
                use_info.alias_map.get(n, n) for n in use_info.imported_names
            ]
            used = any(n in name_usages for n in resolved_names)
            if not used:
                use_info.is_used = False
                msg = f"Unused `use` import: {use_info.full_path}"
                unused.append((use_info, msg, idx))
            else:
                use_info.is_used = True
        return unused

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _collect_use_path_and_names(
        node: Any,
        current_path: str,
        imported_names: list[str],
        alias_map: dict[str, str],
    ) -> None:
        """Recursively walk a ``use_declaration`` subtree to collect
        the import path and imported names."""
        for child in node.children:
            if child.type == "scoped_identifier":
                # Full path like `std::collections::HashMap`
                for part in child.children:
                    if part.type == "identifier":
                        imported_names.append(part.text.decode("utf-8"))
            elif child.type == "identifier":
                # Single identifier like `use foo;`
                imported_names.append(child.text.decode("utf-8"))
            elif child.type == "use_list":
                # `use std::collections::{HashMap, BTreeMap};`
                for list_child in child.children:
                    RustImportAnalyzer._collect_use_path_and_names(
                        list_child, current_path, imported_names, alias_map
                    )
            elif child.type == "use_as_clause":
                # `use Foo as Bar;`
                as_name = None
                original_name = None
                for as_child in child.children:
                    if as_child.type == "identifier":
                        name = as_child.text.decode("utf-8")
                        if original_name is None:
                            original_name = name
                        else:
                            as_name = name
                if original_name and as_name:
                    imported_names.append(as_name)
                    alias_map[as_name] = original_name
            elif child.type in (
                "use_wildcard",  # `use foo::*;`
            ):
                imported_names.append("*")

    @staticmethod
    def _build_use_path(node: Any) -> str:
        """Extract the full module path from a ``use_declaration`` node."""
        path_parts: list[str] = []

        def _walk(n: Any) -> None:
            for child in n.children:
                if child.type == "scoped_identifier":
                    for part in child.children:
                        if part.type == "identifier":
                            path_parts.append(part.text.decode("utf-8"))
                elif child.type == "identifier":
                    path_parts.append(child.text.decode("utf-8"))
                elif child.type == "use_list":
                    pass  # Path prefix is already collected from siblings
                elif child.type == "use_as_clause":
                    for as_child in child.children:
                        if as_child.type == "identifier":
                            path_parts.append(as_child.text.decode("utf-8"))
                            break
                else:
                    _walk(child)

        _walk(node)
        return "::".join(path_parts)
