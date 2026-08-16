# -*- coding: utf-8 -*-
"""TypeScript/JavaScript language backend — adapter implementing
``LanguageAdapter`` for ``.ts`` / ``.tsx`` / ``.js`` / ``.jsx`` files."""

from __future__ import annotations

from typing import Any, Callable

from graphlint.analyzer._types import NodeInfo, ParseResult
from graphlint.analyzer.language.base import LanguageAdapter
from graphlint.analyzer.language.typescript.constants import (
    _TYPESCRIPT_DEFAULT_EXCLUDES,
    _TYPESCRIPT_PUBLIC_API_NAMES,
    _TYPESCRIPT_SPECIAL_NAMES,
    _file_to_module,
    _is_test_file,
)
from graphlint.analyzer.language.typescript.entry import TSEntryPointDetector
from graphlint.analyzer.language.typescript.parser import (
    TSTypeScriptSourceParser,
    _parse_file_worker,
)


class TypeScriptAdapter(LanguageAdapter):
    """Language adapter for TypeScript / JavaScript.

    Requires ``tree-sitter`` + ``tree-sitter-typescript`` +
    ``tree-sitter-javascript``.
    Install: ``pip install graphlint[typescript]``.
    """

    language_name = "typescript"
    file_extensions = frozenset({".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts"})

    def __init__(self, extensions: frozenset[str] | None = None) -> None:
        """Optionally restrict the handled extensions.

        The TypeScript and JavaScript grammars are independent packages;
        the registry passes a restricted set when only one of them is
        installed so files of the missing grammar are skipped (and get the
        standard missing-language hint) instead of failing per file.
        """
        if extensions is not None:
            self.file_extensions = frozenset(extensions)

    @property
    def worker_function(self) -> Callable[..., ParseResult]:
        return _parse_file_worker

    def parse_file(
        self, full_path: str, root_dir: str, config: dict[str, Any]
    ) -> ParseResult:
        parser = TSTypeScriptSourceParser(root_dir, config)
        return parser.parse_file(full_path)

    def detect_entries(
        self,
        parse_results: dict[str, ParseResult],
        nodes: list[NodeInfo],
        node_id_map: dict[int, NodeInfo],
        config: dict[str, Any],
    ) -> list[Any]:
        detector = TSEntryPointDetector(config)
        return detector.detect(parse_results, nodes, node_id_map)

    def file_to_module(self, path: str) -> str:
        return _file_to_module(path)

    def is_test_file(self, file_path: str, config: dict[str, Any]) -> bool:
        return _is_test_file(file_path, config)

    @property
    def public_api_names(self) -> frozenset[str]:
        return _TYPESCRIPT_PUBLIC_API_NAMES

    @property
    def special_names(self) -> frozenset[str]:
        return _TYPESCRIPT_SPECIAL_NAMES

    @property
    def default_excludes(self) -> frozenset[str]:
        return _TYPESCRIPT_DEFAULT_EXCLUDES
