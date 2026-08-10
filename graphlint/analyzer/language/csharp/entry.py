# -*- coding: utf-8 -*-
"""C# entry point detector.

Pattern syntax (same as Python/Rust):

    file_match:<glob>           Match file path against glob
    test_file                   Match test files (uses test_patterns config)
    function_def:<pattern>      Match method/function definitions
    decorator:<pattern>         Match ``[Attribute]`` on types/methods
    class_definition:<pattern>  Match class/struct/record/interface definitions
    visibility:public           Match items with ``public`` visibility
    file_is_program             Match ``Program.cs`` with top-level statements

Patterns support OR with `` | `` (space‑pipe‑space)::

    function_def:Main | decorator:Fact
"""

from __future__ import annotations

import fnmatch
import os
from typing import Any

from graphlint.analyzer._types import EntryInfo, NodeInfo, ParseResult
from graphlint.analyzer.language.csharp.constants import (
    _CSHARP_DEFAULT_DIR_PATTERNS,
    _CSHARP_DEFAULT_FILE_PATTERNS,
    _ensure_csproj_cache,
    _get_csproj_for_file,
)


def _public_api_entry(file_path: str, node: NodeInfo, node_id: int = 0) -> EntryInfo:
    """Build a ``csharp_public_api`` entry for *node*."""
    return EntryInfo(
        rule_name="csharp_public_api",
        file_path=file_path,
        line=node.line_start,
        node_id=node_id,
        description="C# public API entry",
    )


class CSharpEntryPointDetector:
    """Entry point pattern matcher for C# source files.

    Evaluates entry rules against parsed C# CST nodes and file-level
    properties to identify .NET program / test / API entry points.
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

        _ensure_csproj_cache(self.config)
        global_public_as_entry = self.config.get("_public_as_entry", False)

        for file_path, pr in parse_results.items():
            if not file_path.endswith(".cs"):
                continue

            csproj_info = _get_csproj_for_file(file_path, self.config)

            # ---- csproj-driven: test project ----
            if csproj_info and csproj_info.get("is_test_project"):
                entries.append(
                    EntryInfo(
                        rule_name="csproj_test_project",
                        file_path=file_path,
                        line=0,
                        description="C# test project (detected from .csproj)",
                        no_propagate=True,
                    )
                )
                # Test projects don't need entry rule scanning — skip
                continue

            # ---- csproj-driven: library project → public API reachable ----
            # SDK-style projects default to Library when OutputType is absent.
            is_library = bool(csproj_info) and csproj_info.get("output_type", "").lower() not in (
                "exe",
                "winexe",
            )
            file_public_as_entry = global_public_as_entry or is_library

            for rule in self._rules:
                rule_name = rule.get("name", "")
                if not rule_name:
                    continue
                file_pattern = rule.get("file_pattern", "**/*.cs")
                matched = fnmatch.fnmatch(file_path, file_pattern)
                if not matched and file_pattern.startswith("**/"):
                    matched = fnmatch.fnmatch(file_path, file_pattern[3:])
                if not matched:
                    continue
                # File-level rules (file_is_program / test_file /
                # function_call) match whole files; node-level rules
                # match per node and find nothing in node-less files.
                entries.extend(
                    self._detect_rule(rule, file_path, pr, nodes)
                )

            # When public_as_entry is active (global override or library
            # project), treat public items as entries
            if file_public_as_entry:
                entries.extend(
                    self._detect_public_items(file_path, pr, nodes)
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

        # Split OR parts; file-level parts match the whole file, node-level
        # parts match per node.
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
            elif part == "file_is_program":
                entries = self._detect_program_file(rule, file_path, pr)
            elif part.startswith("function_call:"):
                entries = self._match_function_call(
                    part, rule, file_path, pr, nodes
                )
            elif part.startswith("visibility:"):
                vis_target = part.split(":", 1)[1]
                if vis_target == "public":
                    entries = self._detect_public_items_from_rule(
                        rule, file_path, pr, nodes
                    )
            if entries:
                return entries

        # ---- node-level pattern parts ----
        node_parts = [
            p
            for p in or_parts
            if not p.startswith(("file_match:", "function_call:", "visibility:"))
            and p not in ("test_file", "file_is_program")
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
        """Match a ``function_call:<pattern>`` part against the file's calls.

        C# semantics: a ``MapGet`` / ``Application.Run`` call registers the
        surrounding code as an entry (endpoint registration, UI startup).
        The entry targets the method containing the call (resolved through
        the call's source scope); top-level calls (no enclosing method) fall
        back to a file-level entry.
        """
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
            if node.node_type in ("class", "struct", "record", "interface", "enum"):
                return fnmatch.fnmatch(node.name, cls_pattern)

        return False

    # ------------------------------------------------------------------
    # Program file detection (top-level statements, C# 9+)
    # ------------------------------------------------------------------

    def _detect_program_file(
        self,
        rule: dict[str, Any],
        file_path: str,
        pr: ParseResult,
    ) -> list[EntryInfo]:
        """Detect C# 9+ top-level statement files as program entry points.

        A file has top-level statements when the tree-sitter CST root
        contains statements that are not inside any type or namespace
        declaration.  Two complementary signals are used:

        * nodes at file level (``parent_node_id == 0``) that are variables or
          local functions — produced when a top-level statement declares a
          name;
        * references whose source scope is the empty module scope (``""``) —
          produced by top-level calls/reads such as ``Console.WriteLine``
          that declare no name.
        """
        source = pr.source
        if not source:
            return []

        has_top_level = False
        for node in pr.nodes:
            if node.parent_node_id == 0 and node.node_type in ("method", "variable"):
                has_top_level = True
                break

        if not has_top_level:
            for ref in pr.references:
                if not ref.source_qname and ref.edge_type in ("call", "read"):
                    has_top_level = True
                    break

        if not has_top_level:
            return []

        return [
            EntryInfo(
                rule_name=rule.get("name", "csharp_program"),
                file_path=file_path,
                line=1,
                description=rule.get("description", "C# top-level program entry"),
                no_propagate=rule.get("no_propagate", False),
            )
        ]

    # ------------------------------------------------------------------
    # Test file detection
    # ------------------------------------------------------------------

    _CSHARP_TEST_FUNC_PATTERNS: tuple[str, ...] = ("*Test*", "*_Test*")

    def _check_test_file(
        self,
        rule: dict[str, Any],
        file_path: str,
        pr: ParseResult,
    ) -> list[EntryInfo]:
        test_patterns = self.config.get("test_patterns", {})
        file_patterns = test_patterns.get(
            "file_patterns", list(_CSHARP_DEFAULT_FILE_PATTERNS)
        )
        dir_patterns = test_patterns.get(
            "dir_patterns", list(_CSHARP_DEFAULT_DIR_PATTERNS)
        )
        func_patterns = test_patterns.get(
            "function_patterns", list(self._CSHARP_TEST_FUNC_PATTERNS)
        )

        normalized = file_path.replace("\\", "/")
        basename = os.path.basename(file_path)
        dirname = os.path.dirname(file_path).replace(os.sep, "/")

        is_test = any(
            normalized.startswith(d) for d in _CSHARP_DEFAULT_DIR_PATTERNS
        )
        if not is_test:
            is_test = any(fnmatch.fnmatch(basename, p) for p in file_patterns)
        if not is_test:
            dir_with_slash = dirname + "/"
            is_test = any(
                dir_with_slash.startswith(d) or fnmatch.fnmatch(dir_with_slash, d)
                for d in dir_patterns
            )

        if not is_test:
            return []

        # Check for test-related attributes on any type or method
        has_test = any(
            "TestClass" in n.decorators
            or "TestFixture" in n.decorators
            or "Fact" in n.decorators
            or "Theory" in n.decorators
            or "Test" in n.decorators
            or "TestMethod" in n.decorators
            or "TestCase" in n.decorators
            for n in pr.nodes
        )

        if not has_test:
            has_test = any(
                n.node_type in ("method", "function")
                and (
                    any(fnmatch.fnmatch(n.name, p) for p in func_patterns)
                    or n.name.startswith("Test")
                )
                for n in pr.nodes
            )

        if not has_test:
            return []

        return [
            EntryInfo(
                rule_name=rule.get("name", "csharp_test"),
                file_path=file_path,
                line=0,
                description=rule.get("description", "C# test file"),
                no_propagate=rule.get("no_propagate", True),
            )
        ]

    # ------------------------------------------------------------------
    # Public API detection
    # ------------------------------------------------------------------

    def _detect_public_items(
        self, file_path: str, pr: ParseResult, nodes: list[NodeInfo]
    ) -> list[EntryInfo]:
        """Detect all public items as entry points (library API mode).

        C# exposes members implicitly in several places that have no explicit
        ``public`` modifier:

        * enum members — always public; reachable when the enum is public;
        * interface members — always public (no modifier is allowed);
        * explicit indexers / events — public when prefixed with ``public``.

        Visibility is read from the structured ``NodeInfo.visibility`` field
        (parsed from the actual modifier list) rather than from source lines,
        so modifier ordering (``static public``) and multi-line declarations
        are handled correctly.  A member is part of the *public API surface*
        only when it is public **and** every enclosing type is public —
        ``public`` members of ``internal`` types are not externally visible
        and remain analyzable as dead code.
        """
        entries: list[EntryInfo] = []
        parent_map = {n.id: n for n in pr.nodes}
        # Resolve node ids against the *global* node list when provided, so
        # members sharing a line with their container (``public enum Level
        # { Low, High }``) bind to the right node, not the first line match.
        qname_to_gid = {n.qualified_name: n.id for n in nodes}

        def _gid(node: NodeInfo) -> int:
            return qname_to_gid.get(node.qualified_name, 0)

        def _chain_public(n: NodeInfo) -> bool:
            """True when *n* and every enclosing type are public."""
            cur: NodeInfo | None = n
            seen: set[int] = set()
            while cur is not None and cur.id not in seen:
                seen.add(cur.id)
                if cur.node_type in (
                    "class", "struct", "record", "interface", "enum", "delegate",
                ):
                    if cur.visibility != "public":
                        return False
                cur = parent_map.get(cur.parent_node_id)
            return True

        for node in pr.nodes:
            ntype = node.node_type

            if ntype in ("class", "struct", "record", "interface", "enum", "delegate"):
                if node.visibility == "public" and _chain_public(node):
                    entries.append(_public_api_entry(file_path, node, _gid(node)))
                continue

            if ntype == "enum_member":
                parent = parent_map.get(node.parent_node_id)
                if (
                    parent is not None
                    and parent.node_type == "enum"
                    and _chain_public(parent)
                ):
                    entries.append(_public_api_entry(file_path, node, _gid(node)))
                continue

            if ntype in ("method", "property", "indexer", "event", "constructor",
                         "operator", "field"):
                parent = parent_map.get(node.parent_node_id)
                if parent is None:
                    continue
                if parent.node_type == "interface":
                    # Interface members are implicitly public; API contract
                    # only when the interface itself is public.
                    if _chain_public(parent):
                        entries.append(_public_api_entry(file_path, node, _gid(node)))
                elif parent.node_type in ("class", "struct", "record"):
                    # Public API only when the member is public AND every
                    # enclosing type is public.
                    if node.visibility == "public" and _chain_public(parent):
                        entries.append(_public_api_entry(file_path, node, _gid(node)))

        return entries

    def _detect_public_items_from_rule(
        self,
        rule: dict[str, Any],
        file_path: str,
        pr: ParseResult,
        nodes: list[NodeInfo],
    ) -> list[EntryInfo]:
        entries = self._detect_public_items(file_path, pr, nodes)
        rule_name = rule.get("name", "csharp_public_api")
        no_propagate = rule.get("no_propagate", False)
        for entry in entries:
            entry.rule_name = rule_name
            entry.no_propagate = no_propagate
        return entries
