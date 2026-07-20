# -*- coding: utf-8 -*-
"""Entry point detector — matches rules to identify entry points.

All rules (built-in and custom) share the same detection path through
_detect_custom.  The ast_pattern field uses a unified pattern syntax:

    file_match:<glob>           Match file path against glob
    test_file                   Match test files (uses test_patterns config)
    if_name_main                Match ``if __name__ == '__main__':``
    function_call:<pattern>     Match function calls (fnmatch on fully‑qualified name)
    function_def:<pattern>      Match function definitions
    decorator:<pattern>         Match decorators on functions / classes
    class_instantiation:<pattern> Match class instantiation calls

Patterns support OR with `` | `` (space‑pipe‑space)::

    class_instantiation:FastAPI | function_call:uvicorn.run
"""

from __future__ import annotations

import ast
import fnmatch
import os
from dataclasses import dataclass
from typing import Any, Optional

from graphlint.analyzer._types import NodeInfo, ParseResult


@dataclass
class EntryInfo:
    """Entry point information."""

    rule_name: str = ""
    file_path: str = ""
    line: int = 0
    node_id: int = 0
    description: str = ""
    no_propagate: bool = False


class EntryPointDetector:
    """Entry point pattern matcher."""

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
        """Detect entry points across all parse results."""
        entries: list[EntryInfo] = []
        for file_path, pr in parse_results.items():
            for rule in self._rules:
                rule_name = rule.get("name", "")
                if not rule_name:
                    continue
                file_pattern = rule.get("file_pattern", "**/*.py")
                if not fnmatch.fnmatch(file_path, file_pattern):
                    if file_pattern.startswith("**/") and fnmatch.fnmatch(
                        file_path, file_pattern[3:]
                    ):
                        pass
                    else:
                        continue
                if not pr.nodes:
                    continue
                entries.extend(
                    self._detect_custom(rule, file_path, pr, nodes, node_id_map)
                )
        return entries

    @staticmethod
    def update_output(
        entries: list[EntryInfo], node_id_by_key: dict[int, NodeInfo]
    ) -> None:
        """Mark detected entry points on the corresponding NodeInfo."""
        for entry in entries:
            if entry.node_id and entry.node_id in node_id_by_key:
                node = node_id_by_key[entry.node_id]
                if node:
                    node.is_entry = True

    # ------------------------------------------------------------------
    # Unified rule detection (single path for built-in & custom)
    # ------------------------------------------------------------------

    def _detect_custom(
        self,
        rule: dict[str, Any],
        file_path: str,
        pr: ParseResult,
        nodes: list[NodeInfo],
        node_id_map: dict[int, NodeInfo],
    ) -> list[EntryInfo]:
        """Detect entry points matching *rule*.  Handles every pattern type."""
        pattern = rule.get("ast_pattern", "")
        if not pattern:
            return []

        rule_name = rule.get("name", "custom")
        no_propagate = rule.get("no_propagate", False)

        # ---- file_match: (no AST needed) ----
        if pattern.startswith("file_match:"):
            glob_part = pattern.split(":", 1)[1]
            if fnmatch.fnmatch(file_path, glob_part):
                return [
                    EntryInfo(
                        rule_name=rule_name,
                        file_path=file_path,
                        line=1,
                        description=rule.get("description", pattern),
                        no_propagate=no_propagate,
                    )
                ]
            return []

        # ---- test_file: uses test_patterns config ----
        if pattern == "test_file":
            return self._check_test_file(rule, file_path, pr, nodes)

        # ---- AST-based patterns ----
        source = pr.source or self._read_source(file_path)
        if source is None:
            return []
        tree = self._parse_safe(source, file_path)
        if tree is None:
            return []

        entries: list[EntryInfo] = []
        for node in ast.walk(tree):
            if self._check_ast_pattern(pattern, node):
                entries.append(
                    EntryInfo(
                        rule_name=rule_name,
                        file_path=file_path,
                        line=getattr(node, "lineno", 0),
                        description=rule.get("description", pattern),
                        no_propagate=no_propagate,
                    )
                )
        return entries

    def _check_ast_pattern(self, pattern: str, node: ast.AST) -> bool:
        """Check whether *node* matches *pattern* (AST‑level only)."""
        # ---- OR operator (pipe‑separated) ----
        parts = pattern.split(" | ")
        if len(parts) > 1:
            return any(
                self._check_ast_pattern(p.strip(), node) for p in parts
            )

        # ---- pattern prefixes ----
        if pattern.startswith("function_call:"):
            func_pattern = pattern.split(":", 1)[1]
            if isinstance(node, ast.Call):
                return fnmatch.fnmatch(self._call_name(node.func), func_pattern)

        elif pattern.startswith("function_def:"):
            name_pattern = pattern.split(":", 1)[1]
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return fnmatch.fnmatch(node.name, name_pattern)

        elif pattern.startswith("decorator:"):
            dec_pattern = pattern.split(":", 1)[1]
            if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
                for d in getattr(node, "decorator_list", []):
                    d_node = d.func if isinstance(d, ast.Call) else d
                    if fnmatch.fnmatch(self._call_name(d_node), dec_pattern):
                        return True

        elif pattern.startswith("class_instantiation:"):
            cls_pattern = pattern.split(":", 1)[1]
            if isinstance(node, ast.Call):
                return fnmatch.fnmatch(self._call_name(node.func), cls_pattern)

        elif pattern == "if_name_main":
            if isinstance(node, ast.If):
                return self._is_name_main_check(node.test)

        return False

    # ------------------------------------------------------------------
    # Test file detection (pytest_test)
    # ------------------------------------------------------------------

    def _check_test_file(
        self,
        rule: dict[str, Any],
        file_path: str,
        pr: ParseResult,
        nodes: list[NodeInfo],
    ) -> list[EntryInfo]:
        """Detect pytest test files using test_patterns config."""
        test_patterns = self.config.get("test_patterns", {})
        file_patterns = test_patterns.get(
            "file_patterns", ["test_*.py", "*_test.py"]
        )
        dir_patterns = test_patterns.get(
            "dir_patterns", ["tests/", "test/", "__tests__/"]
        )
        func_patterns = test_patterns.get("function_patterns", ["test_*"])

        basename = os.path.basename(file_path)
        dirname = os.path.dirname(file_path).replace(os.sep, "/")

        is_test = any(fnmatch.fnmatch(basename, p) for p in file_patterns)
        if not is_test:
            is_test = any(
                fnmatch.fnmatch(dirname + "/", d) or (dirname + "/").startswith(d)
                for d in dir_patterns
            )
        if not is_test:
            config_files = test_patterns.get("config_files", ["conftest.py"])
            is_test = any(fnmatch.fnmatch(basename, c) for c in config_files)

        if not is_test:
            return []

        has_test = any(
            n.node_type in ("function", "method")
            and any(fnmatch.fnmatch(n.name, p) for p in func_patterns)
            or (n.node_type == "class" and n.name.startswith("Test"))
            for n in pr.nodes
        )

        if not has_test:
            return []

        return [
            EntryInfo(
                rule_name=rule.get("name", "pytest_test"),
                file_path=file_path,
                line=0,
                description=rule.get("description", "pytest test file"),
                no_propagate=rule.get("no_propagate", True),
            )
        ]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_path(self, file_path: str) -> str:
        if isinstance(self.config, dict):
            root = self.config.get("_root_dir", os.getcwd())
        else:
            root = os.getcwd()
        return os.path.join(root, file_path)

    def _read_source(self, file_path: str) -> Optional[str]:
        try:
            with open(self._resolve_path(file_path), "r", encoding="utf-8") as fh:
                return fh.read()
        except OSError:
            return None

    @staticmethod
    def _parse_safe(source: str, filename: str) -> Optional[ast.AST]:
        try:
            return ast.parse(source, filename=filename)
        except SyntaxError:
            return None

    @staticmethod
    def _call_name(func_node: ast.expr) -> str:
        if isinstance(func_node, ast.Name):
            return func_node.id
        if isinstance(func_node, ast.Attribute):
            parts = [func_node.attr]
            current = func_node.value
            while isinstance(current, ast.Attribute):
                parts.append(current.attr)
                current = current.value
            if isinstance(current, ast.Name):
                parts.append(current.id)
            parts.reverse()
            return ".".join(parts)
        return ""

    @staticmethod
    def _is_name_main_check(test: ast.expr) -> bool:
        if isinstance(test, ast.Compare):
            if isinstance(test.left, ast.Name) and test.left.id == "__name__":
                for op, comp in zip(test.ops, test.comparators):
                    if isinstance(op, ast.Eq):
                        if isinstance(comp, ast.Constant) and comp.value == "__main__":
                            return True
        return False
