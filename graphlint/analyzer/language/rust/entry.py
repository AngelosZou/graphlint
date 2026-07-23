# -*- coding: utf-8 -*-
"""Rust entry point detector.

    file_match:<glob>           Match file path against glob
    test_file                   Match test files (uses test_patterns config)
    function_def:<pattern>      Match function definitions (fnmatch on name)
    decorator:<pattern>         Match ``#[...]`` attributes on items
                                (compile-time annotations; no runtime edges)
    visibility:pub              Match items with ``pub`` visibility
    trait_impl:<pattern>        Match trait implementations
    macro_def:<pattern>         Match ``macro_rules!`` definitions

Patterns support OR with `` | `` (space‑pipe‑space)::

    function_def:main | decorator:tokio::main
"""

from __future__ import annotations

import fnmatch
import os
from typing import Any, Optional

from graphlint.analyzer._types import EntryInfo, NodeInfo, ParseResult
from graphlint.analyzer.language.rust.constants import _TREE_SITTER_AVAILABLE


class RustEntryPointDetector:
    """Entry point pattern matcher for Rust source files.

    Evaluates entry rules against parsed Rust CST nodes and file-level
    properties to identify program entry points.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self.config: dict[str, Any] = config
        rules_source = (
            config.get("entry_rules", []) if isinstance(config, dict) else config
        )
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
        """Detect entry points across all parsed Rust files."""
        entries: list[EntryInfo] = []
        for file_path, pr in parse_results.items():
            if not file_path.endswith(".rs"):
                continue
            for rule in self._rules:
                rule_name = rule.get("name", "")
                if not rule_name:
                    continue
                file_pattern = rule.get("file_pattern", "**/*.rs")
                if not fnmatch.fnmatch(file_path, file_pattern):
                    # Check without leading **/
                    if file_pattern.startswith("**/") and fnmatch.fnmatch(
                        file_path, file_pattern[3:]
                    ):
                        pass
                    else:
                        continue
                if not pr.nodes:
                    continue
                entries.extend(
                    self._detect_rule(rule, file_path, pr, nodes, node_id_map)
                )
            # When public_as_entry is active, treat all pub items as
            # entry points independently of config entry rules.
            if self.config.get("_public_as_entry"):
                entries.extend(
                    self._detect_pub_items(
                        {"name": "rust_pub_api", "description": "Rust public API entry (--public-as-entry)"},
                        file_path, pr, nodes,
                    )
                )
        return entries

    # ------------------------------------------------------------------
    # Rule detection (single path for built-in & custom)
    # ------------------------------------------------------------------

    def _detect_rule(
        self,
        rule: dict[str, Any],
        file_path: str,
        pr: ParseResult,
        nodes: list[NodeInfo],
        node_id_map: dict[int, NodeInfo],
    ) -> list[EntryInfo]:
        """Detect entry points matching a single rule."""
        pattern = rule.get("ast_pattern", "")
        if not pattern:
            return []

        rule_name = rule.get("name", "custom")
        no_propagate = rule.get("no_propagate", False)
        description = rule.get("description", pattern)

        # ---- file_match: (no AST needed) ----
        if pattern.startswith("file_match:"):
            glob_part = pattern.split(":", 1)[1]
            if fnmatch.fnmatch(file_path, glob_part):
                return [
                    EntryInfo(
                        rule_name=rule_name,
                        file_path=file_path,
                        line=1,
                        description=description,
                        no_propagate=no_propagate,
                    )
                ]
            return []

        # ---- test_file: uses test_patterns config ----
        if pattern == "test_file":
            return self._check_test_file(rule, file_path, pr, nodes)

        # ---- visibility:pub: match nodes with pub visibility ----
        if pattern.startswith("visibility:"):
            vis_target = pattern.split(":", 1)[1]
            if vis_target == "pub":
                return self._detect_pub_items(rule, file_path, pr, nodes)
            return []

        # ---- Node-based patterns ----
        entries: list[EntryInfo] = []
        for node in pr.nodes:
            if self._check_node_pattern(pattern, node, pr):
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

    def _check_node_pattern(
        self, pattern: str, node: NodeInfo, pr: ParseResult
    ) -> bool:
        """Check whether a :class:`NodeInfo` matches a pattern string."""
        # OR operator
        parts = pattern.split(" | ")
        if len(parts) > 1:
            return any(
                self._check_node_pattern(p.strip(), node, pr) for p in parts
            )

        if pattern.startswith("function_def:"):
            name_pattern = pattern.split(":", 1)[1]
            if node.node_type in ("function", "method"):
                return fnmatch.fnmatch(node.name, name_pattern)

        elif pattern.startswith("decorator:"):
            dec_pattern = pattern.split(":", 1)[1]
            for d in node.decorators:
                if fnmatch.fnmatch(d, dec_pattern):
                    return True

        elif pattern.startswith("trait_impl:"):
            impl_pattern = pattern.split(":", 1)[1]
            if node.node_type in ("struct", "enum", "union"):
                # Check if node has any inherit edges that match
                for ref in pr.references:
                    if (
                        ref.source_qname == node.qualified_name
                        and ref.edge_type == "inherit"
                        and fnmatch.fnmatch(ref.target_name, impl_pattern)
                    ):
                        return True

        elif pattern.startswith("macro_def:"):
            name_pattern = pattern.split(":", 1)[1]
            if node.node_type == "macro":
                return fnmatch.fnmatch(node.name, name_pattern)

        return False

    # ------------------------------------------------------------------
    # Test file detection
    # ------------------------------------------------------------------

    # Rust-native test detection defaults (config overrides these)
    _RUST_TEST_FILE_PATTERNS: tuple[str, ...] = ("test_*.rs", "*_test.rs")
    _RUST_TEST_DIR_PATTERNS: tuple[str, ...] = ("tests/",)
    _RUST_TEST_FUNC_PATTERNS: tuple[str, ...] = ("test_*",)

    def _check_test_file(
        self,
        rule: dict[str, Any],
        file_path: str,
        pr: ParseResult,
        nodes: list[NodeInfo],
    ) -> list[EntryInfo]:
        """Detect Rust test files.

        Rust marks test code via two mechanisms:

        1. **File-path conventions** — integration tests under ``tests/``;
           unit test modules named ``*_test.rs``.

        2. **Source annotations** — ``#[test]`` on individual functions,
           ``#[cfg(test)]`` on modules.  These are the definitive signals.
        """
        test_patterns = self.config.get("test_patterns", {})
        file_patterns = test_patterns.get(
            "file_patterns", list(self._RUST_TEST_FILE_PATTERNS)
        )
        dir_patterns = test_patterns.get(
            "dir_patterns", list(self._RUST_TEST_DIR_PATTERNS)
        )
        func_patterns = test_patterns.get(
            "function_patterns", list(self._RUST_TEST_FUNC_PATTERNS)
        )

        normalized = file_path.replace("\\", "/")
        basename = os.path.basename(file_path)
        dirname = os.path.dirname(file_path).replace(os.sep, "/")

        is_test = normalized.startswith("tests/") or normalized == "tests"
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

        has_test = any(
            n.node_type in ("function", "method")
            and (
                any(fnmatch.fnmatch(n.name, p) for p in func_patterns)
                or n.name.startswith("test_")
            )
            or "test" in n.decorators
            for n in pr.nodes
        )

        if not has_test:
            return []

        return [
            EntryInfo(
                rule_name=rule.get("name", "rust_test"),
                file_path=file_path,
                line=0,
                description=rule.get("description", "Rust test file"),
                no_propagate=rule.get("no_propagate", True),
            )
        ]

    # ------------------------------------------------------------------
    # Pub visibility detection
    # ------------------------------------------------------------------

    def _detect_pub_items(
        self,
        rule: dict[str, Any],
        file_path: str,
        pr: ParseResult,
        nodes: list[NodeInfo],
    ) -> list[EntryInfo]:
        """Return all ``pub`` items as entry points for library crates."""
        entries: list[EntryInfo] = []
        rule_name = rule.get("name", "visibility_pub")
        no_propagate = rule.get("no_propagate", False)
        description = rule.get("description", "pub visibility entry")

        for node in pr.nodes:
            if node.node_type in (
                "function", "method", "struct", "enum", "union",
                "trait", "constant", "type_alias", "module", "macro",
            ):
                # Pub items are detected by checking the source line
                # for a `pub ` or `pub(` prefix.
                source = pr.source
                if source and node.line_start > 0:
                    try:
                        lines = source.split("\n")
                        if node.line_start - 1 < len(lines):
                            line_text = lines[node.line_start - 1].strip()
                            if line_text.startswith("pub ") or line_text.startswith("pub("):
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
                    except (IndexError, AttributeError):
                        pass

        return entries

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_path(self, file_path: str) -> str:
        root = self.config.get("_root_dir", os.getcwd()) if isinstance(self.config, dict) else os.getcwd()
        return os.path.join(root, file_path)

    def _read_source(self, file_path: str) -> Optional[str]:
        try:
            with open(self._resolve_path(file_path), "r", encoding="utf-8") as fh:
                return fh.read()
        except OSError:
            return None
