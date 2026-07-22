# -*- coding: utf-8 -*-
"""Python language backend — adapter implementing LanguageAdapter for .py files."""

from __future__ import annotations

from typing import Any, Callable

from graphlint.analyzer._types import NodeInfo, ParseResult
from graphlint.analyzer.language.base import LanguageAdapter
from graphlint.analyzer.language.python.constants import (
    _PYTHON_DEFAULT_EXCLUDES,
    _PYTHON_PUBLIC_API_DUNDERS,
    _PYTHON_SPECIAL_METHOD_DUNDERS,
    _file_to_module,
    _is_test_file,
)
from graphlint.analyzer.language.python.entry import EntryPointDetector
from graphlint.analyzer.language.python.parser import (
    SourceParser,
    _parse_file_worker,
)


class PythonAdapter(LanguageAdapter):
    """Language adapter for Python (``.py``) source files."""

    language_name = "python"
    file_extensions = frozenset({".py"})
    worker_function: Callable[..., ParseResult] = _parse_file_worker

    def parse_file(
        self, full_path: str, root_dir: str, config: dict[str, Any]
    ) -> ParseResult:
        """Parse a single Python source file."""
        parser = SourceParser(root_dir, config)
        return parser.parse_file(full_path)

    def detect_entries(
        self,
        parse_results: dict[str, ParseResult],
        nodes: list[NodeInfo],
        node_id_map: dict[int, NodeInfo],
        config: dict[str, Any],
    ) -> list[Any]:
        """Detect Python entry points (__main__, framework apps, tests, etc.)."""
        detector = EntryPointDetector(config)
        return detector.detect(parse_results, nodes, node_id_map)

    def file_to_module(self, path: str) -> str:
        """Convert ``pkg/mod.py`` → ``"pkg.mod"``."""
        return _file_to_module(path)

    def is_test_file(self, file_path: str, config: dict[str, Any]) -> bool:
        """Check whether *file_path* is a Python test file."""
        return _is_test_file(file_path, config)

    @property
    def public_api_names(self) -> frozenset[str]:
        """Python module-level dunder names with well-defined semantics."""
        return _PYTHON_PUBLIC_API_DUNDERS

    @property
    def special_names(self) -> frozenset[str]:
        """Python data-model dunder method names invoked implicitly by the runtime."""
        return _PYTHON_SPECIAL_METHOD_DUNDERS

    @property
    def default_excludes(self) -> frozenset[str]:
        """Default exclude patterns for Python project directories."""
        return _PYTHON_DEFAULT_EXCLUDES
