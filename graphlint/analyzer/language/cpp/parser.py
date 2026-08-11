# -*- coding: utf-8 -*-
"""C++ source parser — tree-sitter-cpp based parsing."""

from __future__ import annotations

import os
from typing import Any

from graphlint.analyzer._types import ParseResult
from graphlint.analyzer.language.cpp.constants import (
    _TREE_SITTER_CPP_AVAILABLE,
    _file_to_module,
    _get_cpp_language,
)
from graphlint.analyzer.language.cpp.imports import CppImportAnalyzer
from graphlint.analyzer.language.cpp.visitor import CppVisitor


class CppSourceParser:
    """Parse a single C++ source file into structured nodes, references,
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

        if not _TREE_SITTER_CPP_AVAILABLE:
            result.warnings.append(
                _make_warning(
                    "missing_dependency", "error",
                    "tree-sitter-cpp is not installed. "
                    "Install with: pip install graphlint[cpp]",
                    file_path,
                )
            )
            return result

        try:
            import tree_sitter
            lang = _get_cpp_language()
            parser = tree_sitter.Parser()
            parser.language = lang

            tree = parser.parse(source.encode("utf-8"))
        except Exception as exc:
            result.warnings.append(
                _make_warning(
                    "parse_error", "error",
                    f"Parse failed for {file_path}: {exc}", file_path,
                )
            )
            return result

        module_qname = _file_to_module(file_path)
        import_analyzer = CppImportAnalyzer()
        visitor = CppVisitor(module_qname, file_path, import_analyzer)
        visitor.visit(tree)

        result.nodes = visitor.nodes
        result.references = visitor.references
        result.name_usages = visitor.name_usages
        result.warnings.extend(visitor.warnings)

        for include_info in visitor.uses:
            result.imports.append({
                "target": include_info.target,
                "is_system": include_info.is_system,
                "line": include_info.line,
            })

        return result


def _read_source(full_path: str) -> str | None:
    """Read source file content."""
    try:
        with open(full_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except (OSError, UnicodeDecodeError):
        return None


def _make_warning(warn_type: str, severity: str, message: str,
                  file_path: str) -> Any:
    from graphlint.analyzer.warnings import WarningInfo
    return WarningInfo(
        warn_type=warn_type, severity=severity, message=message,
        file_path=file_path,
    )


# ---------------------------------------------------------------------------
# Module-level worker for adapter registration
# ---------------------------------------------------------------------------

_parser_instances: dict[str, CppSourceParser] = {}


def _parse_file_worker(
    full_path: str, root_dir: str, config: dict[str, Any],
) -> ParseResult:
    """Parse a single C++ source file.  Cached per *root_dir* config."""
    cache_key = root_dir
    parser = _parser_instances.get(cache_key)
    if parser is None:
        parser = CppSourceParser(root_dir, config)
        _parser_instances[cache_key] = parser
    return parser.parse_file(full_path)
