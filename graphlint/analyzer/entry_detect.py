# -*- coding: utf-8 -*-
"""Entry point detector — matches rules to identify entry points."""

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

    _BUILTIN_DETECTORS: dict[str, str] = {
        "python_main": "_detect_python_main",
        "python_package": "_detect_python_package",
        "fastapi_app": "_detect_fastapi_app",
        "flask_app": "_detect_flask_app",
        "django_manage": "_detect_django_manage",
        "click_command": "_detect_click_command",
        "typer_app": "_detect_typer_app",
        "celery_app": "_detect_celery_app",
        "pytest_plugin": "_detect_pytest_plugin",
        "pytest_test": "_detect_pytest_test",
    }

    def __init__(self, config: dict[str, Any]) -> None:
        self.config: dict[str, Any] = config
        # Supports dict format ({"entry_rules": [...]}) or direct list format
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
                    # Also match root-level files (fnmatch **/ requires /)
                    if file_pattern.startswith("**/") and fnmatch.fnmatch(
                        file_path, file_pattern[3:]
                    ):
                        pass
                    else:
                        continue
                if not pr.nodes:
                    continue
                detector_method = self._BUILTIN_DETECTORS.get(rule_name)
                if detector_method:
                    method = getattr(self, detector_method, None)
                    if method:
                        entries.extend(method(file_path, pr, nodes, node_id_map))
                else:
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
    # Built-in rule detectors
    # ------------------------------------------------------------------

    def _detect_python_main(
        self,
        file_path: str,
        pr: ParseResult,
        nodes: list[NodeInfo],
        node_id_map: dict[int, NodeInfo],
    ) -> list[EntryInfo]:
        """Detect if __name__ == '__main__' entry."""
        source = pr.source or self._read_source(file_path)
        if source is None:
            return []
        tree = self._parse_safe(source, file_path)
        if tree is None:
            return []
        entries: list[EntryInfo] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.If) and self._is_name_main_check(node.test):
                entries.append(
                    EntryInfo(
                        rule_name="python_main",
                        file_path=file_path,
                        line=node.lineno,
                        description="if __name__ == '__main__':",
                    )
                )
        return entries

    def _detect_python_package(
        self,
        file_path: str,
        pr: ParseResult,
        nodes: list[NodeInfo],
        node_id_map: dict[int, NodeInfo],
    ) -> list[EntryInfo]:
        """Detect __init__.py files as package API entry points."""
        if os.path.basename(file_path) != "__init__.py":
            return []
        # Skip test package __init__.py files
        if isinstance(self.config, dict):
            test_patterns = self.config.get("test_patterns", {})
            dir_patterns = test_patterns.get(
                "dir_patterns", ["tests/", "test/", "__tests__/"]
            )
            dirname = os.path.dirname(file_path).replace(os.sep, "/")
            is_test_dir = any(
                fnmatch.fnmatch(dirname + "/", d) or (dirname + "/").startswith(d)
                for d in dir_patterns
            )
            if is_test_dir:
                return []
        return [
            EntryInfo(
                rule_name="python_package",
                file_path=file_path,
                line=0,
                description="Package __init__.py",
            )
        ]

    def _detect_fastapi_app(
        self,
        file_path: str,
        pr: ParseResult,
        nodes: list[NodeInfo],
        node_id_map: dict[int, NodeInfo],
    ) -> list[EntryInfo]:
        """Detect FastAPI application entry."""
        src = pr.source
        entries = self._detect_framework_call(file_path, ["FastAPI"], source=src)
        entries.extend(
            self._detect_framework_call(file_path, [], ["uvicorn.run", "uvicorn"], source=src)
        )
        for e in entries:
            e.rule_name = "fastapi_app"
        return entries

    def _detect_flask_app(
        self,
        file_path: str,
        pr: ParseResult,
        nodes: list[NodeInfo],
        node_id_map: dict[int, NodeInfo],
    ) -> list[EntryInfo]:
        """Detect Flask application entry."""
        src = pr.source
        entries = self._detect_framework_call(file_path, ["Flask", "flask.Flask"], source=src)
        # Also detect .run() calls
        source = src or self._read_source(file_path)
        if source is None:
            return entries
        tree = self._parse_safe(source, file_path)
        if tree is None:
            return entries
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = self._call_name(node.func)
                if name.endswith(".run"):
                    entries.append(
                        EntryInfo(
                            rule_name="flask_app",
                            file_path=file_path,
                            line=node.lineno,
                            description=f"{name}()",
                        )
                    )
        return entries

    def _detect_django_manage(
        self,
        file_path: str,
        pr: ParseResult,
        nodes: list[NodeInfo],
        node_id_map: dict[int, NodeInfo],
    ) -> list[EntryInfo]:
        """Detect Django manage.py entry."""
        if file_path.split("/")[-1] != "manage.py":
            return []
        return self._detect_framework_call(file_path, ["execute_from_command_line"], source=pr.source)

    def _detect_click_command(
        self,
        file_path: str,
        pr: ParseResult,
        nodes: list[NodeInfo],
        node_id_map: dict[int, NodeInfo],
    ) -> list[EntryInfo]:
        """Detect Click CLI entry (@click.command / @click.group)."""
        entries: list[EntryInfo] = []
        for node in pr.nodes:
            for d in node.decorators or []:
                if "click.command" in d or "click.group" in d:
                    entries.append(
                        EntryInfo(
                            rule_name="click_command",
                            file_path=file_path,
                            line=node.line_start,
                            description=f"@{d}",
                        )
                    )
        return entries

    def _detect_typer_app(
        self,
        file_path: str,
        pr: ParseResult,
        nodes: list[NodeInfo],
        node_id_map: dict[int, NodeInfo],
    ) -> list[EntryInfo]:
        """Detect Typer CLI entry."""
        entries = self._detect_framework_call(file_path, ["typer.Typer"], source=pr.source)
        for e in entries:
            e.rule_name = "typer_app"
        for node in pr.nodes:
            for d in node.decorators or []:
                if d.endswith(".command") or ".command(" in d:
                    entries.append(
                        EntryInfo(
                            rule_name="typer_app",
                            file_path=file_path,
                            line=node.line_start,
                            description=f"@{d}",
                        )
                    )
        return entries

    def _detect_celery_app(
        self,
        file_path: str,
        pr: ParseResult,
        nodes: list[NodeInfo],
        node_id_map: dict[int, NodeInfo],
    ) -> list[EntryInfo]:
        """Detect Celery application entry."""
        entries = self._detect_framework_call(file_path, ["Celery", "celery.Celery"], source=pr.source)
        for e in entries:
            e.rule_name = "celery_app"
        return entries

    def _detect_pytest_plugin(
        self,
        file_path: str,
        pr: ParseResult,
        nodes: list[NodeInfo],
        node_id_map: dict[int, NodeInfo],
    ) -> list[EntryInfo]:
        """Detect Pytest plugin/config entry."""
        if file_path.split("/")[-1] != "conftest.py":
            return []
        entries: list[EntryInfo] = []
        for node in pr.nodes:
            if node.node_type == "function" and node.name == "pytest_addoption":
                entries.append(
                    EntryInfo(
                        rule_name="pytest_plugin",
                        file_path=file_path,
                        line=node.line_start,
                        description="pytest_addoption",
                    )
                )
            for d in node.decorators or []:
                if "pytest.fixture" in d:
                    entries.append(
                        EntryInfo(
                            rule_name="pytest_plugin",
                            file_path=file_path,
                            line=node.line_start,
                            description=f"@{d}",
                        )
                    )
        return entries

    def _detect_pytest_test(
        self,
        file_path: str,
        pr: ParseResult,
        nodes: list[NodeInfo],
        node_id_map: dict[int, NodeInfo],
    ) -> list[EntryInfo]:
        """Detect pytest test files as entry points."""
        test_patterns = self.config.get("test_patterns", {})
        file_patterns = test_patterns.get("file_patterns", ["test_*.py", "*_test.py"])
        dir_patterns = test_patterns.get(
            "dir_patterns", ["tests/", "test/", "__tests__/"]
        )
        func_patterns = test_patterns.get("function_patterns", ["test_*"])

        basename = os.path.basename(file_path)
        dirname = os.path.dirname(file_path).replace(os.sep, "/")

        # Check file name pattern
        is_test = any(fnmatch.fnmatch(basename, p) for p in file_patterns)
        # Check directory pattern
        if not is_test:
            is_test = any(
                fnmatch.fnmatch(dirname + "/", d) or (dirname + "/").startswith(d)
                for d in dir_patterns
            )
        # Check config files
        if not is_test:
            config_files = test_patterns.get("config_files", ["conftest.py"])
            is_test = any(fnmatch.fnmatch(basename, c) for c in config_files)

        if not is_test:
            return []

        # Check if file contains test functions/classes
        has_test = any(
            n.node_type in ("function", "method")
            and any(fnmatch.fnmatch(n.name, p) for p in func_patterns)
            or (n.node_type == "class" and n.name.startswith("Test"))
            for n in pr.nodes
        )

        if not has_test:
            return []

        # File-level entry: all nodes reachable; test entries do not propagate.
        return [
            EntryInfo(
                rule_name="pytest_test",
                file_path=file_path,
                line=0,
                description="pytest test file",
                no_propagate=True,
            )
        ]

    # ------------------------------------------------------------------
    # Custom rule detection
    # ------------------------------------------------------------------

    def _detect_custom(
        self,
        rule: dict[str, Any],
        file_path: str,
        pr: ParseResult,
        nodes: list[NodeInfo],
        node_id_map: dict[int, NodeInfo],
    ) -> list[EntryInfo]:
        """Detect custom entry rules."""
        pattern = rule.get("ast_pattern", "")
        if not pattern:
            return []
        source = pr.source or self._read_source(file_path)
        if source is None:
            return []
        tree = self._parse_safe(source, file_path)
        if tree is None:
            return []
        entries: list[EntryInfo] = []
        for node in ast.walk(tree):
            if self._check_ast_pattern(pattern, node, source):
                entries.append(
                    EntryInfo(
                        rule_name=rule.get("name", "custom"),
                        file_path=file_path,
                        line=getattr(node, "lineno", 0),
                        description=f"custom:{pattern}",
                    )
                )
        return entries

    def _check_ast_pattern(self, pattern: str, node: ast.AST, source: str) -> bool:
        """Check whether an AST node matches a custom rule pattern."""
        if pattern.startswith("function_call:"):
            func_name = pattern.split(":", 1)[1]
            if isinstance(node, ast.Call):
                return self._call_name(node.func) == func_name
        elif pattern.startswith("function_def:"):
            name_pattern = pattern.split(":", 1)[1]
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                return fnmatch.fnmatch(node.name, name_pattern)
        elif pattern.startswith("decorator:"):
            dec_name = pattern.split(":", 1)[1]
            if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
                for d in getattr(node, "decorator_list", []):
                    d_node = d.func if isinstance(d, ast.Call) else d
                    if dec_name in self._call_name(d_node):
                        return True
        elif pattern.startswith("class_instantiation:"):
            cls_name = pattern.split(":", 1)[1]
            if isinstance(node, ast.Call):
                return self._call_name(node.func) == cls_name
        elif pattern.startswith("file_match:"):
            return fnmatch.fnmatch(
                getattr(node, "filename", ""), pattern.split(":", 1)[1]
            )
        return False

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

    def _detect_framework_call(
        self,
        file_path: str,
        class_names: list[str],
        extra_names: Optional[list[str]] = None,
        source: Optional[str] = None,
    ) -> list[EntryInfo]:
        """Generic framework call detection."""
        if source is None:
            source = self._read_source(file_path)
            if source is None:
                return []
        tree = self._parse_safe(source, file_path)
        if tree is None:
            return []
        entries: list[EntryInfo] = []
        all_names = set(class_names)
        if extra_names:
            all_names.update(extra_names)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = self._call_name(node.func)
                if name in all_names:
                    entries.append(
                        EntryInfo(
                            file_path=file_path,
                            line=node.lineno,
                            description=f"{name}() call",
                        )
                    )
        return entries
