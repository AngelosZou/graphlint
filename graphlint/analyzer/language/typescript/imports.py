# -*- coding: utf-8 -*-
"""TypeScript/JavaScript import analyzer — resolves ES module and CommonJS
imports/exports."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ImportInfo:
    """Resolved import/require information."""

    module_path: str = ""
    imported_names: list[str] = field(default_factory=list)
    default_import: str = ""
    namespace_import: str = ""
    alias_map: dict[str, str] = field(default_factory=dict)
    is_type_import: bool = False
    line: int = 0


@dataclass
class ExportInfo:
    """Resolved export information."""

    module_path: str = ""
    exported_names: list[str] = field(default_factory=list)
    default_export: str = ""
    namespace_export: str = ""
    is_type_export: bool = False
    line: int = 0


class TSTypeScriptImportAnalyzer:
    """Analyzes ES module import/export and CommonJS require statements."""

    def analyze_import(self, node: Any) -> ImportInfo | None:
        """Analyze a tree-sitter ``import_statement`` node.

        Handles:
            - ``import X from 'module'``
            - ``import { X, Y } from 'module'``
            - ``import * as X from 'module'``
            - ``import 'module'`` (side-effect)
            - ``import type { X } from 'module'``
        """
        module_path = ""
        imported_names: list[str] = []
        default_import = ""
        namespace_import = ""
        alias_map: dict[str, str] = {}
        is_type_import = False

        source_node = node.child_by_field_name("source")
        if source_node and source_node.type == "string":
            module_path = _unquote(_node_text(source_node))

        # Check for ``import type``
        for child in node.children:
            if child.type == "type":
                is_type_import = True
                break

        # Parse import clause
        clause = node.child_by_field_name("import_clause") or node.child_by_field_name(
            "clause"
        )
        if clause is None:
            # Check children directly
            for child in node.children:
                if child.type == "import_clause":
                    clause = child
                    break

        if clause is not None:
            # Default import: import X from ...
            for child in clause.children:
                if child.type == "identifier":
                    default_import = _node_text(child)
                    imported_names.append(default_import)
                    break

            # Named imports: import { X, Y as Z } from ...
            for child in clause.children:
                if child.type == "named_imports":
                    for spec in child.children:
                        if spec.type == "import_specifier":
                            name_node = spec.child_by_field_name("name")
                            alias_node = spec.child_by_field_name("alias")
                            if name_node:
                                name = _node_text(name_node)
                                imported_names.append(name)
                                if alias_node:
                                    alias_map[name] = _node_text(alias_node)
                        elif spec.type == "identifier":
                            spec_name = _node_text(spec)
                            if spec_name not in imported_names:
                                imported_names.append(spec_name)

            # Namespace import: import * as X from ...
            for child in clause.children:
                if child.type == "namespace_import":
                    ns_node = child.child_by_field_name("name")
                    # Alternative: namespace_import has identifier child
                    if ns_node:
                        namespace_import = _node_text(ns_node)
                        imported_names.append(namespace_import)
                    else:
                        for c in child.children:
                            if c.type == "identifier":
                                namespace_import = _node_text(c)
                                imported_names.append(namespace_import)
                                break

        if not imported_names and module_path:
            imported_names.append("*")

        line = _node_line(node)

        return ImportInfo(
            module_path=module_path,
            imported_names=imported_names,
            default_import=default_import,
            namespace_import=namespace_import,
            alias_map=alias_map,
            is_type_import=is_type_import,
            line=line,
        )

    def analyze_require(self, node: Any) -> ImportInfo | None:
        """Analyze a CommonJS ``require('module')`` call expression."""
        for child in node.children:
            if child.type == "arguments":
                for arg in child.children:
                    if arg.type == "string":
                        module_path = _unquote(_node_text(arg))
                        line = _node_line(node)
                        return ImportInfo(
                            module_path=module_path,
                            imported_names=["*"],
                            line=line,
                        )
        return None

    def analyze_export(self, node: Any) -> ExportInfo | None:
        """Analyze a tree-sitter ``export_statement`` node.

        Handles:
            - ``export { X, Y as Z }``  (and ``export { X } from 'module'``)
            - ``export * from 'module'`` / ``export * as ns from 'module'``
            - ``export default <expr>``
            - ``export default function foo() {}`` / ``export default class A {}``
            - declaration exports: ``export const foo = 1`` / ``export function f`` /
              ``export class C`` / ``export enum E`` / ``export interface I`` /
              ``export type T = ...``
            - ``export type { X }``
        """
        exported_names: list[str] = []
        default_export = ""
        namespace_export = ""
        module_path = ""
        is_type_export = False

        for child in node.children:
            if child.type == "type":
                is_type_export = True
                break

        # Re-export: export { X } from 'module' / export * from 'module'
        source_node = node.child_by_field_name("source")
        if source_node and source_node.type == "string":
            module_path = _unquote(_node_text(source_node))

        has_default = any(c.type == "default" for c in node.children)

        for child in node.children:
            if child.type == "default":
                default_export = "default"
                continue
            if child.type == "export_clause":
                for sub in child.children:
                    if sub.type == "named_exports":
                        for spec in sub.children:
                            if spec.type == "export_specifier":
                                name_node = spec.child_by_field_name("name")
                                alias_node = spec.child_by_field_name("alias")
                                # The name importers use is the alias when present
                                # (``export { X as Y }`` -> Y), else the raw name.
                                # The local symbol (raw name) is also exported, so
                                # record both for entry detection.
                                if name_node:
                                    exported_names.append(_node_text(name_node))
                                if alias_node:
                                    exported_names.append(_node_text(alias_node))
                    elif sub.type == "namespace_export":
                        ns_node = sub.child_by_field_name("name")
                        if ns_node:
                            namespace_export = _node_text(ns_node)
                        else:
                            for c in sub.children:
                                if c.type == "identifier":
                                    namespace_export = _node_text(c)
                                    break
                        if namespace_export:
                            exported_names.append(namespace_export)
                continue
            if child.type == "identifier":
                # ``export default app`` — the exported name is the identifier.
                exported_names.append(_node_text(child))
                continue
            # Declaration exports: export const/let/var/function/class/...
            if child.type in ("lexical_declaration", "variable_declaration"):
                for decl in child.children:
                    if decl.type == "variable_declarator":
                        name_node = decl.child_by_field_name("name")
                        if name_node and name_node.type == "identifier":
                            exported_names.append(_node_text(name_node))
                continue
            if child.type in (
                "function_declaration",
                "generator_function_declaration",
                "class_declaration",
                "abstract_class_declaration",
                "interface_declaration",
                "enum_declaration",
                "type_alias_declaration",
            ):
                name_node = child.child_by_field_name("name")
                if name_node:
                    exported_names.append(_node_text(name_node))
                continue

        # A default export exposes the name ``default`` to importers.
        if has_default and "default" not in exported_names:
            exported_names.append("default")

        line = _node_line(node)

        return ExportInfo(
            module_path=module_path,
            exported_names=exported_names,
            default_export=default_export,
            namespace_export=namespace_export,
            is_type_export=is_type_export,
            line=line,
        )

    # ------------------------------------------------------------------
    # Unused-import detection
    # ------------------------------------------------------------------

    def detect_unused_imports(
        self,
        uses: list[ImportInfo],
        name_usages: set[str],
        file_path: str = "",
    ) -> list[tuple[ImportInfo, str, int]]:
        """Detect unused ``import`` / ``require`` directives.

        - Side-effect imports (``import "x"`` -> ``["*"]``) are skipped — the
          module may register global behaviour we cannot see in one file.
        - Type-only imports (``import type { X }``) are skipped — types are
          erased at compile time and usage lives in type positions that cannot
          all be captured reliably.
        - Each named/default/namespace import is checked against *name_usages*.
        - For ``import { X as Y }`` the *alias* ``Y`` is what code references,
          so the alias (or the raw name when there is no alias) is checked.
        """
        unused: list[tuple[ImportInfo, str, int]] = []
        for imp in uses:
            if imp.imported_names == ["*"]:
                continue
            if imp.is_type_import:
                continue

            # Report EACH unused binding (an `import { A, B }` may partially
            # use A while B is never referenced) rather than dropping the whole
            # import when any name is used.
            unused_names: list[str] = []
            for raw_name in imp.imported_names:
                # The name code actually references is the alias if present
                # (``import { X as Y }`` -> used as ``Y``), else the raw name.
                local_name = imp.alias_map.get(raw_name, raw_name)
                if local_name not in name_usages:
                    unused_names.append(raw_name)

            for name in unused_names:
                msg = f"'{name}' imported but not used"
                unused.append((imp, msg, imp.line))

        return unused


def _node_text(node: Any) -> str:
    """Decode tree-sitter node text safely."""
    try:
        return node.text.decode("utf-8") if node.text else ""
    except (UnicodeDecodeError, AttributeError):
        return ""


def _node_line(node: Any) -> int:
    try:
        return (node.start_point[0] + 1) if node.start_point else 0
    except (AttributeError, IndexError, TypeError):
        return 0


def _unquote(s: str) -> str:
    """Strip surrounding quotes from a string literal."""
    s = s.strip()
    if (s.startswith("'") and s.endswith("'")) or (s.startswith('"') and s.endswith('"')):
        return s[1:-1]
    if s.startswith("`") and s.endswith("`"):
        return s[1:-1]
    return s
