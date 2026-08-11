# -*- coding: utf-8 -*-
"""C++ language backend — adapter implementing ``LanguageAdapter`` for
``.cpp/.hpp`` files."""

from __future__ import annotations

from typing import Any, Callable

from graphlint.analyzer._types import NodeInfo, ParseResult
from graphlint.analyzer.language.base import LanguageAdapter
from graphlint.analyzer.language.cpp.constants import (
    _CPP_DEFAULT_EXCLUDES,
    _CPP_PUBLIC_API_NAMES,
    _CPP_SPECIAL_NAMES,
    _CPP_EXTENSIONS,
    _file_to_module,
    _is_test_file,
)
from graphlint.analyzer.language.cpp.entry import CppEntryPointDetector
from graphlint.analyzer.language.cpp.parser import (
    CppSourceParser,
    _parse_file_worker,
)


class CppAdapter(LanguageAdapter):
    """Language adapter for C++ (``.cpp``, ``.hpp``, etc.) files.

    Requires ``tree-sitter`` + ``tree-sitter-cpp``.
    Install: ``pip install graphlint[cpp]``.
    """

    language_name = "cpp"
    file_extensions = _CPP_EXTENSIONS

    @property
    def worker_function(self) -> Callable[..., ParseResult]:
        return _parse_file_worker

    def parse_file(
        self, full_path: str, root_dir: str, config: dict[str, Any]
    ) -> ParseResult:
        parser = CppSourceParser(root_dir, config)
        return parser.parse_file(full_path)

    def detect_entries(
        self,
        parse_results: dict[str, ParseResult],
        nodes: list[NodeInfo],
        node_id_map: dict[int, NodeInfo],
        config: dict[str, Any],
    ) -> list[Any]:
        detector = CppEntryPointDetector(config)
        return detector.detect(parse_results, nodes, node_id_map)

    def file_to_module(self, path: str) -> str:
        return _file_to_module(path)

    def is_test_file(self, file_path: str, config: dict[str, Any]) -> bool:
        return _is_test_file(file_path, config)

    @property
    def public_api_names(self) -> frozenset[str]:
        return _CPP_PUBLIC_API_NAMES

    @property
    def special_names(self) -> frozenset[str]:
        return _CPP_SPECIAL_NAMES

    @property
    def default_excludes(self) -> frozenset[str]:
        return _CPP_DEFAULT_EXCLUDES
