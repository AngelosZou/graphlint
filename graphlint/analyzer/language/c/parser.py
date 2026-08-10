# -*- coding: utf-8 -*-
"""C source parser — tree-sitter-c based parsing for ``.c`` / ``.h`` files."""

from __future__ import annotations

import os
from typing import Any

from graphlint.analyzer._types import ParseResult
from graphlint.analyzer.language.c.constants import (
    _TREE_SITTER_C_AVAILABLE,
    _file_to_module,
    _get_c_language,
)
from graphlint.analyzer.language.c.imports import CImportAnalyzer
from graphlint.analyzer.language.c.visitor import CVisitor


class CSourceParser:
    """Parse a single C source file into structured nodes, references,
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

        if not _TREE_SITTER_C_AVAILABLE:
            result.warnings.append(
                _make_warning(
                    "syntax_error", "error",
                    "tree-sitter-c not installed; install with: "
                    "pip install graphlint[c]",
                    file_path,
                )
            )
            return result

        try:
            lang = _get_c_language()
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
            import_analyzer = CImportAnalyzer()
            visitor = CVisitor(module_qname, file_path, import_analyzer)
            visitor.visit(tree)
            visitor.finalize()

            result.nodes = visitor.nodes
            result.imports = visitor.imports
            result.name_usages = visitor.name_usages
            result.references = visitor.references
            result.warnings.extend(visitor.warnings)
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
    parser = CSourceParser(root_dir, config)
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
