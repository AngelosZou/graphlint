# -*- coding: utf-8 -*-
"""TypeScript/JavaScript source parser — tree-sitter based parsing."""

from __future__ import annotations

import os
from typing import Any

from graphlint.analyzer._types import ParseResult
from graphlint.analyzer.language.typescript.constants import (
    _TREE_SITTER_TYPESCRIPT_AVAILABLE,
    _TREE_SITTER_JAVASCRIPT_AVAILABLE,
    _file_to_module,
    _get_parser_language_for_file,
)
from graphlint.analyzer.language.typescript.imports import TSTypeScriptImportAnalyzer
from graphlint.analyzer.language.typescript.visitor import TSTypeScriptVisitor


class TSTypeScriptSourceParser:
    """Parse a single TS/JS source file into structured nodes, references,
    and imports."""

    def __init__(self, root_dir: str, config: dict[str, Any]) -> None:
        self.root_dir = root_dir
        self.config = config

    def parse_file(self, full_path: str) -> ParseResult:
        """Parse *full_path* and return a :class:`ParseResult`."""
        file_path = os.path.relpath(full_path, self.root_dir).replace(os.sep, "/")
        result = ParseResult(file_path=file_path)

        try:
            source = _read_source(full_path)
            if source is None:
                result.warnings.append(
                    _make_warning(
                        "parse_error", "error",
                        f"Cannot read file: {file_path}", file_path,
                    )
                )
                return result
            result.source = source
        except Exception:
            result.warnings.append(
                _make_warning(
                    "parse_error", "error",
                    f"Read error: {file_path}", file_path,
                )
            )
            return result

        if not _TREE_SITTER_TYPESCRIPT_AVAILABLE and not _TREE_SITTER_JAVASCRIPT_AVAILABLE:
            result.warnings.append(
                _make_warning(
                    "syntax_error", "error",
                    "tree-sitter-typescript not installed; install with: "
                    "pip install graphlint[typescript]",
                    file_path,
                )
            )
            return result

        try:
            lang = _get_parser_language_for_file(file_path)
            import tree_sitter

            parser = tree_sitter.Parser()
            if hasattr(parser, "set_language"):
                parser.set_language(lang)
            else:
                parser.language = lang
            tree = parser.parse(bytes(source, "utf-8"))
        except Exception as exc:
            result.warnings.append(
                _make_warning(
                    "syntax_error", "error",
                    f"Parse error in {file_path}: {exc}", file_path,
                )
            )
            return result

        try:
            module_qname = _file_to_module(file_path)
            import_analyzer = TSTypeScriptImportAnalyzer()
            visitor = TSTypeScriptVisitor(module_qname, file_path, import_analyzer)
            visitor.visit(tree)

            result.nodes = visitor.nodes
            result.imports = list(visitor.imports)
            result.name_usages = visitor.name_usages
            result.references = visitor.references
            result.warnings.extend(visitor.warnings)
            result.exports = list(visitor.exports)
            result.exported_names = visitor.exported_names

            # Unused-import detection (mirrors python/rust backends).
            unused = import_analyzer.detect_unused_imports(
                result.imports, result.name_usages, file_path
            )
            for unused_imp, msg, line in unused:
                result.warnings.append(
                    _make_warning(
                        "unused_import", "warning", msg, file_path, line=line
                    )
                )
        except Exception as exc:
            result.warnings.append(
                _make_warning(
                    "syntax_error", "error",
                    f"Visit error in {file_path}: {exc}", file_path,
                )
            )

        return result


def _parse_file_worker(full_path: str, root_dir: str, config: dict[str, Any]) -> ParseResult:
    """Module-level worker for ProcessPoolExecutor (must be picklable)."""
    parser = TSTypeScriptSourceParser(root_dir, config)
    return parser.parse_file(full_path)


def _read_source(path: str) -> str | None:
    """Read source file content, handling encoding issues."""
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            with open(path, "r", encoding=enc) as fh:
                return fh.read()
        except UnicodeDecodeError:
            continue
        except OSError:
            return None
    return None


def _make_warning(
    warn_type: str,
    severity: str,
    message: str,
    file_path: str,
    line: int = 0,
    node_id: int = 0,
) -> Any:
    from graphlint.analyzer.warnings import WarningInfo
    return WarningInfo(
        warn_type=warn_type,
        severity=severity,
        message=message,
        file_path=file_path,
        line=line,
        node_id=node_id,
    )
