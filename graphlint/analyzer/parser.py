# -*- coding: utf-8 -*-
"""AST parser — recursively walks target directory, extracts structured information."""

from __future__ import annotations

import ast
import os
from typing import Any, Optional

from graphlint.analyzer._ast_visitor import ASTVisitor
from graphlint.analyzer._types import ParseResult
from graphlint.analyzer.decorators import DecoratorResolver
from graphlint.analyzer.imports import ImportAnalyzer
from graphlint.analyzer.warnings import (
    WarningInfo,
    detect_file_too_large,
)
from graphlint.storage.hashing import compute_file_hash


class SourceParser:
    """Python source code AST parser."""

    def __init__(self, root_dir: str, config: dict[str, Any]) -> None:
        self.root_dir = os.path.realpath(root_dir)
        self.config = config
        self.import_analyzer = ImportAnalyzer(self.root_dir)
        self.decorator_resolver = DecoratorResolver()

    def parse_file(self, full_path: str = "", rel_path: str = "") -> ParseResult:
        """Parse a single Python file."""
        if not rel_path and full_path:
            rel_path = os.path.relpath(full_path, self.root_dir).replace(os.sep, "/")
        result = ParseResult(file_path=rel_path)
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
            tree = ast.parse(content, filename=rel_path)
        except SyntaxError as exc:
            result.warnings.append(
                WarningInfo(
                    warn_type="syntax_error",
                    severity="error",
                    message=f"Syntax error: {exc.msg}",
                    file_path=rel_path,
                    line=exc.lineno or 0,
                )
            )
            return result
        result.tree = tree
        module_q = self._file_to_module(rel_path)
        visitor = ASTVisitor(
            module_qualified=module_q,
            file_path=rel_path,
            import_analyzer=self.import_analyzer,
            decorator_resolver=self.decorator_resolver,
        )
        visitor.visit(tree)
        result.nodes, result.imports = visitor.nodes, visitor.imports
        result.name_usages = visitor.name_usages
        result.references = visitor.references
        unused = self.import_analyzer.detect_unused_imports(
            result.imports,
            result.name_usages,
            rel_path,
        )
        for imp, msg, _ in unused:
            result.warnings.append(
                WarningInfo(
                    warn_type="unused_import",
                    severity="warning",
                    message=msg,
                    file_path=rel_path,
                    line=imp.line,
                )
            )
        return result

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
        if path.endswith(".py"):
            path = path[:-3]
        return path.replace("/", ".").replace("\\", ".")


# Module-level worker function for ProcessPoolExecutor (must be picklable)
def _parse_file_worker(
    file_path: str, root_dir: str, config: dict[str, Any]
) -> ParseResult:
    parser = SourceParser(root_dir, config)
    return parser.parse_file(file_path)
