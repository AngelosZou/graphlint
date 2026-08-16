# -*- coding: utf-8 -*-
"""TypeScript/JavaScript entry point detector.

Pattern syntax (same as Python/Rust/C#):

    file_match:<glob>           Match file path against glob
    test_file                   Match test files (uses test_patterns config)
    function_def:<pattern>      Match function/method definitions
    decorator:<pattern>         Match ``@decorator`` on classes/methods
    class_definition:<pattern>  Match class/interface definitions
    function_call:<pattern>     Match function calls
    class_instantiation:<p>     Match ``new Class()`` expressions
    jsx_element:<p>             Match JSX elements (React components)
    export:<pattern>            Match exported symbols

Patterns support OR with `` | `` (space‑pipe‑space)::

    function_def:main | function_call:app.listen
"""

from __future__ import annotations

import fnmatch
import os
from typing import Any

from graphlint.analyzer._types import EntryInfo, NodeInfo, ParseResult
from graphlint.analyzer.language.typescript.constants import (
    _TS_DEFAULT_DIR_PATTERNS,
    _TS_DEFAULT_FILE_PATTERNS,
    _is_test_file,
)


class TSEntryPointDetector:
    """Entry point pattern matcher for TypeScript/JavaScript source files.

    Evaluates entry rules against parsed TS/JS CST nodes and file-level
    properties to identify program/test/API entry points.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self.config: dict[str, Any] = config
        rules_source = config.get("entry_rules", [])
        self._rules: list[dict[str, Any]] = [
            r for r in rules_source if r.get("enabled", True)
        ]

    # ------------------------------------------------------------------
    # Main detection entry
    # ------------------------------------------------------------------

    def detect(
        self,
        parse_results: dict[str, ParseResult],
        nodes: list[NodeInfo],
        node_id_map: dict[int, NodeInfo],
    ) -> list[EntryInfo]:
        entries: list[EntryInfo] = []

        global_public_as_entry = self.config.get("_public_as_entry", False)

        # Decision (owner review point D): package.json/tsconfig-driven library
        # detection (like the C# csproj path) is intentionally NOT implemented
        # here. The ``--public-as-entry`` flag remains the explicit signal for
        # "every export is an entry". Adding project-metadata detection is
        # documented as a follow-up to keep this adapter minimal and avoid
        # surprising implicit reachability changes.

        for file_path, pr in parse_results.items():
            if not any(
                file_path.endswith(ext)
                for ext in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts")
            ):
                continue

            for rule in self._rules:
                rule_name = rule.get("name", "")
                if not rule_name:
                    continue
                file_pattern = rule.get("file_pattern", "**/*")
                matched = fnmatch.fnmatch(file_path, file_pattern)
                if not matched and file_pattern.startswith("**/"):
                    matched = fnmatch.fnmatch(file_path, file_pattern[3:])
                if not matched:
                    continue
                entries.extend(
                    self._detect_rule(rule, file_path, pr, nodes)
                )

            # When public_as_entry is active (library project), treat exports as entries
            if global_public_as_entry:
                entries.extend(
                    self._detect_public_exports(file_path, pr, nodes)
                )

        return entries

    # ------------------------------------------------------------------
    # Rule detection
    # ------------------------------------------------------------------

    def _detect_rule(
        self,
        rule: dict[str, Any],
        file_path: str,
        pr: ParseResult,
        nodes: list[NodeInfo],
    ) -> list[EntryInfo]:
        pattern = rule.get("ast_pattern", "")
        if not pattern:
            return []

        rule_name = rule.get("name", "custom")
        no_propagate = rule.get("no_propagate", False)
        description = rule.get("description", pattern)

        or_parts = [p.strip() for p in pattern.split(" | ") if p.strip()]
        if not or_parts:
            return []

        # ---- file-level pattern parts ----
        for part in or_parts:
            entries: list[EntryInfo] = []
            if part.startswith("file_match:"):
                glob_val = part.split(":", 1)[1]
                if fnmatch.fnmatch(file_path, glob_val):
                    entries.append(
                        EntryInfo(
                            rule_name=rule_name,
                            file_path=file_path,
                            line=1,
                            description=description,
                            no_propagate=no_propagate,
                        )
                    )
            elif part == "test_file":
                entries = self._check_test_file(rule, file_path, pr)
            elif part.startswith("function_call:"):
                entries = self._match_function_call(
                    part, rule, file_path, pr, nodes
                )
            elif part.startswith("class_instantiation:"):
                entries = self._match_class_instantiation(
                    part, rule, file_path, pr, nodes
                )
            elif part.startswith("jsx_element:"):
                entries = self._match_jsx_element(
                    part, rule, file_path, pr, nodes
                )
            elif part.startswith("export:"):
                entries = self._match_export(
                    part, rule, file_path, pr, nodes
                )
            if entries:
                return entries

        # ---- node-level pattern parts ----
        node_parts = [
            p
            for p in or_parts
            if not p.startswith((
                "file_match:", "function_call:", "class_instantiation:",
                "jsx_element:", "export:",
            ))
            and p not in ("test_file",)
        ]
        if not node_parts:
            return []

        entries: list[EntryInfo] = []
        for node in pr.nodes:
            if self._check_node_pattern(" | ".join(node_parts), node, file_path):
                entries.append(
                    EntryInfo(
                        rule_name=rule_name,
                        file_path=file_path,
                        line=node.line_start,
                        node_id=0,
                        description=description,
                        no_propagate=no_propagate,
                    )
                )
        return entries

    def _match_function_call(
        self,
        part: str,
        rule: dict[str, Any],
        file_path: str,
        pr: ParseResult,
        nodes: list[NodeInfo],
    ) -> list[EntryInfo]:
        name_pattern = part.split(":", 1)[1]
        qname_to_global = {n.qualified_name: n.id for n in nodes}
        entries: list[EntryInfo] = []
        for ref in pr.references:
            if ref.edge_type != "call":
                continue
            if not fnmatch.fnmatch(ref.target_name, name_pattern):
                continue
            nid = qname_to_global.get(ref.source_qname, 0)
            entries.append(
                EntryInfo(
                    rule_name=rule.get("name", "custom"),
                    file_path=file_path,
                    line=ref.line,
                    node_id=nid,
                    description=rule.get("description", part),
                    no_propagate=rule.get("no_propagate", False),
                )
            )
        return entries

    def _match_class_instantiation(
        self,
        part: str,
        rule: dict[str, Any],
        file_path: str,
        pr: ParseResult,
        nodes: list[NodeInfo],
    ) -> list[EntryInfo]:
        name_pattern = part.split(":", 1)[1]
        qname_to_global = {n.qualified_name: n.id for n in nodes}
        entries: list[EntryInfo] = []
        for ref in pr.references:
            if ref.edge_type != "call":
                continue
            if not ref.target_name.endswith(".constructor"):
                continue
            base = ref.target_name.replace(".constructor", "")
            if not fnmatch.fnmatch(base, name_pattern):
                continue
            nid = qname_to_global.get(ref.source_qname, 0)
            entries.append(
                EntryInfo(
                    rule_name=rule.get("name", "custom"),
                    file_path=file_path,
                    line=ref.line,
                    node_id=nid,
                    description=rule.get("description", part),
                    no_propagate=rule.get("no_propagate", False),
                )
            )
        return entries

    def _match_jsx_element(
        self,
        part: str,
        rule: dict[str, Any],
        file_path: str,
        pr: ParseResult,
        nodes: list[NodeInfo],
    ) -> list[EntryInfo]:
        name_pattern = part.split(":", 1)[1]
        qname_to_global = {n.qualified_name: n.id for n in nodes}
        entries: list[EntryInfo] = []
        for ref in pr.references:
            if ref.edge_type != "jsx_element":
                continue
            if not fnmatch.fnmatch(ref.target_name, name_pattern):
                continue
            nid = qname_to_global.get(ref.source_qname, 0)
            entries.append(
                EntryInfo(
                    rule_name=rule.get("name", "custom"),
                    file_path=file_path,
                    line=ref.line,
                    node_id=nid,
                    description=rule.get("description", part),
                    no_propagate=rule.get("no_propagate", False),
                )
            )
        return entries

    def _match_export(
        self,
        part: str,
        rule: dict[str, Any],
        file_path: str,
        pr: ParseResult,
        nodes: list[NodeInfo],
    ) -> list[EntryInfo]:
        name_pattern = part.split(":", 1)[1]
        qname_to_global = {n.qualified_name: n.id for n in nodes}
        exported = getattr(pr, "exported_names", set())
        entries: list[EntryInfo] = []
        for node in pr.nodes:
            if node.name not in exported and node.qualified_name not in exported:
                continue
            if not fnmatch.fnmatch(node.name, name_pattern):
                continue
            nid = qname_to_global.get(node.qualified_name, 0)
            entries.append(
                EntryInfo(
                    rule_name=rule.get("name", "custom"),
                    file_path=file_path,
                    line=node.line_start,
                    node_id=nid,
                    description=rule.get("description", part),
                    no_propagate=rule.get("no_propagate", False),
                )
            )
        return entries

    # ------------------------------------------------------------------
    # Pattern matching on NodeInfo
    # ------------------------------------------------------------------

    def _check_node_pattern(
        self, pattern: str, node: NodeInfo, file_path: str
    ) -> bool:
        parts = pattern.split(" | ")
        if len(parts) > 1:
            return any(
                self._check_node_pattern(p.strip(), node, file_path) for p in parts
            )

        if pattern.startswith("function_def:"):
            name_pattern = pattern.split(":", 1)[1]
            if node.node_type in ("method", "function"):
                return fnmatch.fnmatch(node.name, name_pattern)

        elif pattern.startswith("decorator:"):
            dec_pattern = pattern.split(":", 1)[1]
            for d in node.decorators:
                if fnmatch.fnmatch(d, dec_pattern):
                    return True

        elif pattern.startswith("class_definition:"):
            cls_pattern = pattern.split(":", 1)[1]
            if node.node_type in ("class", "interface", "type_alias", "enum", "namespace"):
                return fnmatch.fnmatch(node.name, cls_pattern)

        return False

    # ------------------------------------------------------------------
    # Test file detection
    # ------------------------------------------------------------------

    _TS_TEST_FUNC_PATTERNS: tuple[str, ...] = ("*test*", "*spec*", "it", "describe")

    def _check_test_file(
        self,
        rule: dict[str, Any],
        file_path: str,
        pr: ParseResult,
    ) -> list[EntryInfo]:
        if not _is_test_file(file_path, self.config):
            return []

        test_patterns = self.config.get("test_patterns", {})
        func_patterns = test_patterns.get(
            "function_patterns", list(self._TS_TEST_FUNC_PATTERNS)
        )

        has_test = any(
            n.node_type in ("method", "function")
            and any(fnmatch.fnmatch(n.name, p) for p in func_patterns)
            for n in pr.nodes
        )

        if not has_test:
            return []

        return [
            EntryInfo(
                rule_name=rule.get("name", "ts_test"),
                file_path=file_path,
                line=0,
                description=rule.get("description", "TypeScript test file"),
                no_propagate=rule.get("no_propagate", True),
            )
        ]

    # ------------------------------------------------------------------
    # Public export detection (library mode)
    # ------------------------------------------------------------------

    def _detect_public_exports(
        self, file_path: str, pr: ParseResult, nodes: list[NodeInfo]
    ) -> list[EntryInfo]:
        """Treat exported symbols as entry points (library API mode).

        Only symbols actually exported by the file (recorded in
        ``ParseResult.exported_names`` by the visitor) become entries — an
        un-exported declaration is private and must not seed reachability.
        """
        entries: list[EntryInfo] = []
        qname_to_global = {n.qualified_name: n.id for n in nodes}
        exported = getattr(pr, "exported_names", set())

        for node in pr.nodes:
            if node.name not in exported and node.qualified_name not in exported:
                continue
            nid = qname_to_global.get(node.qualified_name, 0)
            entries.append(
                EntryInfo(
                    rule_name="ts_public_export",
                    file_path=file_path,
                    line=node.line_start,
                    node_id=nid,
                    description="Exported symbol (library entry)",
                )
            )

        return entries
