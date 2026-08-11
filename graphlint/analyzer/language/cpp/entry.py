# -*- coding: utf-8 -*-
"""C++ entry point detector.

Pattern syntax (same as Python/Rust/C#):

    function_def:<pattern>      Match function/method definitions
    class_definition:<pattern>  Match class/struct definitions
    file_match:<glob>           Match file path against glob
    test_file                   Match test files (uses test_patterns config)

Patterns support OR with `` | `` (space‑pipe‑space)::

    function_def:main | function_def:WinMain
"""

from __future__ import annotations

import fnmatch
import os
from typing import Any

from graphlint.analyzer._types import EntryInfo, NodeInfo, ParseResult
from graphlint.analyzer.language.cpp.constants import (
    _CPP_DEFAULT_DIR_PATTERNS,
    _CPP_DEFAULT_FILE_PATTERNS,
)

# ---------------------------------------------------------------------------
# C++ entry patterns — matching ``main`` / ``WinMain`` / test entry points
# ---------------------------------------------------------------------------
_CPP_TEST_FUNC_PATTERNS: tuple[str, ...] = ("*Test*", "*_Test*", "test_*")


def _fnmatch_brace(path: str, pattern: str) -> bool:
    """fnmatch that expands ``{a,b,...}`` brace patterns."""
    import re

    # Fast path: no braces
    if "{" not in pattern:
        return fnmatch.fnmatch(path, pattern)

    brace_match = re.fullmatch(r"^(.*?)\{([^}]+)\}(.*)$", pattern)
    if brace_match is None:
        return fnmatch.fnmatch(path, pattern)

    prefix = brace_match.group(1)
    suffix = brace_match.group(3)
    alternatives = [alt.strip() for alt in brace_match.group(2).split(",")]

    return any(
        fnmatch.fnmatch(path, prefix + alt + suffix) for alt in alternatives
    )


class CppEntryPointDetector:
    """Entry point pattern matcher for C++ source files."""

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

        for file_path, pr in parse_results.items():
            if not _is_cpp_file(file_path):
                continue

            for rule in self._rules:
                rule_name = rule.get("name", "")
                if not rule_name:
                    continue
                file_pattern = rule.get("file_pattern", "**/*")
                matched = _fnmatch_brace(file_path, file_pattern)
                if not matched and file_pattern.startswith("**/"):
                    matched = _fnmatch_brace(file_path, file_pattern[3:])
                if not matched:
                    continue
                entries.extend(
                    self._detect_rule(rule, file_path, pr, nodes)
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
                if _fnmatch_brace(file_path, glob_val):
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
            if entries:
                return entries

        # ---- node-level pattern parts ----
        entries: list[EntryInfo] = []
        for node in pr.nodes:
            if any(
                self._check_node_pattern(part, node) for part in or_parts
                if not part.startswith("file_match:") and part != "test_file"
            ):
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

    # ------------------------------------------------------------------
    # Pattern matching on NodeInfo
    # ------------------------------------------------------------------

    def _check_node_pattern(self, pattern: str, node: NodeInfo) -> bool:
        if pattern.startswith("function_def:"):
            name_pattern = pattern.split(":", 1)[1]
            if node.node_type in ("method", "function"):
                return fnmatch.fnmatch(node.name, name_pattern)
        elif pattern.startswith("class_definition:"):
            cls_pattern = pattern.split(":", 1)[1]
            if node.node_type in ("class", "struct", "union", "enum"):
                return fnmatch.fnmatch(node.name, cls_pattern)
        return False

    # ------------------------------------------------------------------
    # Test file detection
    # ------------------------------------------------------------------

    def _check_test_file(
        self,
        rule: dict[str, Any],
        file_path: str,
        pr: ParseResult,
    ) -> list[EntryInfo]:
        test_patterns = self.config.get("test_patterns", {})
        file_patterns = test_patterns.get(
            "file_patterns", list(_CPP_DEFAULT_FILE_PATTERNS)
        )
        dir_patterns = test_patterns.get(
            "dir_patterns", list(_CPP_DEFAULT_DIR_PATTERNS)
        )
        func_patterns = test_patterns.get(
            "function_patterns", list(_CPP_TEST_FUNC_PATTERNS)
        )

        normalized = file_path.replace("\\", "/")
        basename = os.path.basename(file_path)
        dirname = os.path.dirname(file_path).replace(os.sep, "/")

        is_test = any(
            normalized.startswith(d) for d in _CPP_DEFAULT_DIR_PATTERNS
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

        # Check for test-named functions
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
                rule_name=rule.get("name", "cpp_test"),
                file_path=file_path,
                line=0,
                description=rule.get("description", "C++ test file"),
                no_propagate=rule.get("no_propagate", True),
            )
        ]


def _is_cpp_file(path: str) -> bool:
    """Check if *path* is a C++ source file."""
    from graphlint.analyzer.language.cpp.constants import _CPP_EXTENSIONS
    for ext in _CPP_EXTENSIONS:
        if path.endswith(ext):
            return True
    return False
