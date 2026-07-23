# -*- coding: utf-8 -*-
"""Rust language backend — adapter implementing ``LanguageAdapter`` for ``.rs`` files."""

from __future__ import annotations

from typing import Any, Callable

from graphlint.analyzer._types import NodeInfo, ParseResult
from graphlint.analyzer.language.base import LanguageAdapter
from graphlint.analyzer.language.rust.constants import (
    _RUST_DEFAULT_EXCLUDES,
    _RUST_PUBLIC_API_NAMES,
    _RUST_SPECIAL_NAMES,
    _TREE_SITTER_AVAILABLE,
    _file_to_module,
    _is_test_file,
)
from graphlint.analyzer.language.rust.entry import RustEntryPointDetector
from graphlint.analyzer.language.rust.parser import (
    RustSourceParser,
    _parse_file_worker,
)


class RustAdapter(LanguageAdapter):
    """Language adapter for Rust (``.rs``) files.

    Requires ``tree-sitter`` + ``tree-sitter-rust``.
    Install: ``pip install graphlint[rust]``.
    """

    language_name = "rust"
    file_extensions = frozenset({".rs"})

    @property
    def worker_function(self) -> Callable[..., ParseResult]:
        """Module-level worker for ProcessPoolExecutor (must be picklable)."""
        return _parse_file_worker

    def parse_file(
        self, full_path: str, root_dir: str, config: dict[str, Any]
    ) -> ParseResult:
        parser = RustSourceParser(root_dir, config)
        return parser.parse_file(full_path)

    def detect_entries(
        self,
        parse_results: dict[str, ParseResult],
        nodes: list[NodeInfo],
        node_id_map: dict[int, NodeInfo],
        config: dict[str, Any],
    ) -> list[Any]:
        detector = RustEntryPointDetector(config)
        return detector.detect(parse_results, nodes, node_id_map)

    def file_to_module(self, path: str) -> str:
        return _file_to_module(path)

    def is_test_file(self, file_path: str, config: dict[str, Any]) -> bool:
        return _is_test_file(file_path, config)

    @property
    def public_api_names(self) -> frozenset[str]:
        return _RUST_PUBLIC_API_NAMES

    @property
    def special_names(self) -> frozenset[str]:
        return _RUST_SPECIAL_NAMES

    @property
    def default_excludes(self) -> frozenset[str]:
        return _RUST_DEFAULT_EXCLUDES
