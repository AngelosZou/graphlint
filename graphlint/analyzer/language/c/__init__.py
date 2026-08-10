# -*- coding: utf-8 -*-
"""C language backend — adapter implementing ``LanguageAdapter`` for
``.c`` and ``.h`` files."""

from __future__ import annotations

from typing import Any, Callable

from graphlint.analyzer._types import NodeInfo, ParseResult
from graphlint.analyzer.language.base import LanguageAdapter
from graphlint.analyzer.language.c.constants import (
    _C_DEFAULT_EXCLUDES,
    _C_PUBLIC_API_NAMES,
    _C_SPECIAL_NAMES,
    _file_to_module,
    _is_test_file,
)
from graphlint.analyzer.language.c.entry import CEntryPointDetector
from graphlint.analyzer.language.c.parser import CSourceParser, _parse_file_worker

_C_ENTRY_FUNCTION_NAMES: frozenset[str] = frozenset({
    "main",
    "Main",
    "WinMain",
    "wWinMain",
    "DllMain",
    "_tmain",
})


class CAdapter(LanguageAdapter):
    """Language adapter for C (``.c`` / ``.h``) files.

    Requires ``tree-sitter`` + ``tree-sitter-c``.
    Install: ``pip install graphlint[c]``.
    """

    language_name = "c"
    file_extensions = frozenset({".c", ".h"})

    @property
    def worker_function(self) -> Callable[..., ParseResult]:
        return _parse_file_worker

    def parse_file(
        self, full_path: str, root_dir: str, config: dict[str, Any]
    ) -> ParseResult:
        parser = CSourceParser(root_dir, config)
        return parser.parse_file(full_path)

    def detect_entries(
        self,
        parse_results: dict[str, ParseResult],
        nodes: list[NodeInfo],
        node_id_map: dict[int, NodeInfo],
        config: dict[str, Any],
    ) -> list[Any]:
        detector = CEntryPointDetector(config)
        return detector.detect(parse_results, nodes, node_id_map)

    def file_to_module(self, path: str) -> str:
        return _file_to_module(path)

    def is_test_file(self, file_path: str, config: dict[str, Any]) -> bool:
        return _is_test_file(file_path, config)

    def is_special_name(self, name: str) -> bool:
        if name in self.special_names:
            return True
        return name in _C_ENTRY_FUNCTION_NAMES

    @property
    def public_api_names(self) -> frozenset[str]:
        return _C_PUBLIC_API_NAMES

    @property
    def special_names(self) -> frozenset[str]:
        return _C_SPECIAL_NAMES

    @property
    def default_excludes(self) -> frozenset[str]:
        return _C_DEFAULT_EXCLUDES
