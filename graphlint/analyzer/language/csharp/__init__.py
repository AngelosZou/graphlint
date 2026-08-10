# -*- coding: utf-8 -*-
"""C# language backend — adapter implementing ``LanguageAdapter`` for
``.cs`` files."""

from __future__ import annotations

from typing import Any, Callable

from graphlint.analyzer._types import NodeInfo, ParseResult
from graphlint.analyzer.language.base import LanguageAdapter
from graphlint.analyzer.language.csharp.constants import (
    _CSHARP_DEFAULT_EXCLUDES,
    _CSHARP_PUBLIC_API_NAMES,
    _CSHARP_SPECIAL_NAMES,
    _ensure_csproj_cache,
    _file_to_module,
    _is_property_accessor,
    _is_test_file,
    _module_qname_for_file,
)
from graphlint.analyzer.language.csharp.entry import CSharpEntryPointDetector
from graphlint.analyzer.language.csharp.parser import (
    CSharpSourceParser,
    _parse_file_worker,
)


class CSharpAdapter(LanguageAdapter):
    """Language adapter for C# (``.cs``) files.

    Requires ``tree-sitter`` + ``tree-sitter-c-sharp``.
    Install: ``pip install graphlint[csharp]``.
    """

    language_name = "csharp"
    file_extensions = frozenset({".cs"})

    @property
    def worker_function(self) -> Callable[..., ParseResult]:
        return _parse_file_worker

    def parse_file(
        self, full_path: str, root_dir: str, config: dict[str, Any]
    ) -> ParseResult:
        parser = CSharpSourceParser(root_dir, config)
        return parser.parse_file(full_path)

    def detect_entries(
        self,
        parse_results: dict[str, ParseResult],
        nodes: list[NodeInfo],
        node_id_map: dict[int, NodeInfo],
        config: dict[str, Any],
    ) -> list[Any]:
        _ensure_csproj_cache(config)
        detector = CSharpEntryPointDetector(config)
        return detector.detect(parse_results, nodes, node_id_map)

    def file_to_module(self, path: str) -> str:
        return _file_to_module(path)

    def file_to_module_with_csproj(self, path: str, config: dict[str, Any]) -> str:
        """Convert file path to module name, using csproj root_namespace."""
        return _module_qname_for_file(path, config)

    def is_test_file(self, file_path: str, config: dict[str, Any]) -> bool:
        return _is_test_file(file_path, config)

    @property
    def public_api_names(self) -> frozenset[str]:
        return _CSHARP_PUBLIC_API_NAMES

    @property
    def special_names(self) -> frozenset[str]:
        return _CSHARP_SPECIAL_NAMES

    def is_special_name(self, name: str) -> bool:
        """Check if *name* is an implicitly-invoked special name.

        Also matches property accessors (``get_Name`` / ``set_Name`` /
        ``init_Name``) which are called implicitly by the C# compiler.
        """
        if name in self.special_names:
            return True
        return _is_property_accessor(name)

    @property
    def default_excludes(self) -> frozenset[str]:
        return _CSHARP_DEFAULT_EXCLUDES
