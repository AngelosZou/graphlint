# -*- coding: utf-8 -*-
"""Rust source parser — reads `.rs` files, parses via tree-sitter, and produces
:class:`ParseResult` objects for the graph-builder pipeline."""

from __future__ import annotations

import os
from typing import Any, Optional

from graphlint.analyzer._types import ParseResult
from graphlint.analyzer.language.rust.constants import (
    _TREE_SITTER_AVAILABLE,
    _get_rust_language,
)
from graphlint.analyzer.language.rust.imports import RustImportAnalyzer
from graphlint.analyzer.language.rust.visitor import RustVisitor
from graphlint.analyzer.warnings import (
    WarningInfo,
    detect_file_too_large,
)
from graphlint.storage.hashing import compute_file_hash


class RustSourceParser:
    """Parses a single Rust (``.rs``) source file via tree-sitter.

    On construction the parser loads the tree-sitter Rust grammar.
    Each call to :meth:`parse_file` produces a :class:`ParseResult`
    with nodes, references, imports, and warnings.
    """

    def __init__(self, root_dir: str, config: dict[str, Any]) -> None:
        self.root_dir = os.path.realpath(root_dir)
        self.config = config
        self.import_analyzer = RustImportAnalyzer()

    def parse_file(self, full_path: str = "", rel_path: str = "") -> ParseResult:
        """Parse a single Rust source file.

        Args:
            full_path: Absolute path to the ``.rs`` file.
            rel_path: Relative path (computed from *full_path* if empty).

        Returns:
            A :class:`ParseResult` containing nodes, references, imports,
            name usages, and any parse-time warnings.
        """
        if not rel_path and full_path:
            rel_path = os.path.relpath(full_path, self.root_dir).replace(os.sep, "/")
        result = ParseResult(file_path=rel_path)

        if not _TREE_SITTER_AVAILABLE:
            result.warnings.append(
                WarningInfo(
                    warn_type="syntax_error",
                    severity="error",
                    message=(
                        "tree-sitter-rust is not installed. "
                        "Install with: pip install graphlint[rust]"
                    ),
                    file_path=rel_path,
                )
            )
            return result

        content_bytes = self._read_bytes(full_path, result)
        if content_bytes is None:
            return result

        result.hash = compute_file_hash(full_path)
        max_mb = self.config.get("performance", {}).get("max_file_size_mb", 10)
        too_large = detect_file_too_large(rel_path, len(content_bytes), max_mb)
        if too_large:
            result.warnings.append(too_large)
            return result

        content = self._decode(content_bytes, result)
        if content is None:
            return result

        result.source = content

        try:
            lang = _get_rust_language()
            tree_sitter_module = __import__("tree_sitter")
            parser_cls = getattr(tree_sitter_module, "Parser")
            parser = parser_cls()
            # tree-sitter >= 0.24 uses a property, older versions use set_language()
            if hasattr(parser, "set_language"):
                parser.set_language(lang)
            else:
                parser.language = lang
            tree = parser.parse(bytes(content, "utf-8"))
        except Exception as exc:
            result.warnings.append(
                WarningInfo(
                    warn_type="syntax_error",
                    severity="error",
                    message=f"Tree-sitter parse error: {exc}",
                    file_path=rel_path,
                )
            )
            return result

        crate_q = self._file_to_module(rel_path)
        visitor = RustVisitor(
            crate_qualified=crate_q,
            file_path=rel_path,
            import_analyzer=self.import_analyzer,
        )
        visitor.visit(tree)

        result.nodes = visitor.nodes
        result.imports = getattr(visitor, "uses", [])
        result.name_usages = visitor.name_usages
        result.references = visitor.references

        unused = self.import_analyzer.detect_unused_imports(
            result.imports, result.name_usages, rel_path
        )
        for use_info, msg, _ in unused:
            result.warnings.append(
                WarningInfo(
                    warn_type="unused_import",
                    severity="warning",
                    message=msg,
                    file_path=rel_path,
                    line=use_info.line,
                )
            )

        return result

    # ------------------------------------------------------------------
    # I/O helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _read_bytes(fp: str, result: ParseResult) -> Optional[bytes]:
        try:
            with open(fp, "rb") as fh:
                return fh.read()
        except OSError as exc:
            result.warnings.append(
                WarningInfo(
                    warn_type="syntax_error",
                    severity="error",
                    message=f"Cannot read file: {exc}",
                    file_path=result.file_path,
                )
            )
            return None

    @staticmethod
    def _decode(data: bytes, result: ParseResult) -> Optional[str]:
        for enc in ("utf-8", "latin-1"):
            try:
                return data.decode(enc)
            except UnicodeDecodeError:
                continue
        result.warnings.append(
            WarningInfo(
                warn_type="syntax_error",
                severity="error",
                message="Cannot decode file",
                file_path=result.file_path,
            )
        )
        return None

    @staticmethod
    def _file_to_module(path: str) -> str:
        from graphlint.analyzer.language.rust.constants import _file_to_module

        return _file_to_module(path)


# ---------------------------------------------------------------------------
# Module-level worker for ProcessPoolExecutor (must be picklable)
# ---------------------------------------------------------------------------


def _parse_file_worker(
    file_path: str, root_dir: str, config: dict[str, Any]
) -> ParseResult:
    """Parse a Rust source file (module-level, picklable).

    Signature matches :attr:`~graphlint.analyzer.language.base.LanguageAdapter.worker_function`.
    """
    parser = RustSourceParser(root_dir, config)
    return parser.parse_file(file_path)
