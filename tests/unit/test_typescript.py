# -*- coding: utf-8 -*-
"""Tests for the TypeScript/JavaScript language adapter."""

from __future__ import annotations

import os
import tempfile
from typing import Any

import pytest

from graphlint.analyzer._types import GraphBuildResult, NodeInfo
from graphlint.analyzer.warnings import WarningCollector
from graphlint.analyzer.language.typescript.constants import (
    _TYPESCRIPT_DEFAULT_EXCLUDES,
    _TYPESCRIPT_PUBLIC_API_NAMES,
    _TYPESCRIPT_SPECIAL_NAMES,
    _TREE_SITTER_TYPESCRIPT_AVAILABLE,
    _file_to_module,
    _is_js_file,
    _is_test_file,
    _is_ts_file,
    _is_tsx_file,
)
from graphlint.analyzer.language.typescript.imports import TSTypeScriptImportAnalyzer
from graphlint.analyzer.language.typescript.visitor import TSTypeScriptVisitor


tree_sitter_available = pytest.mark.skipif(
    not _TREE_SITTER_TYPESCRIPT_AVAILABLE, reason="tree-sitter-typescript not installed"
)


# =============================================================================
# Constants tests (always runnable)
# =============================================================================


class TestTypeScriptConstants:
    def test_is_ts_file(self):
        assert _is_ts_file("components/Button.ts") is True
        assert _is_ts_file("src/index.mts") is True
        assert _is_ts_file("a.tsx") is True  # TSX is a TS superset
        assert _is_ts_file("a.js") is False
        assert _is_ts_file("a.py") is False

    def test_is_tsx_file(self):
        assert _is_tsx_file("App.tsx") is True
        assert _is_tsx_file("App.ts") is False
        assert _is_tsx_file("App.jsx") is True
        assert _is_tsx_file("App.js") is False

    def test_is_js_file(self):
        assert _is_js_file("app.js") is True
        assert _is_js_file("app.jsx") is True
        assert _is_js_file("app.mjs") is True
        assert _is_js_file("app.cjs") is True
        assert _is_js_file("app.ts") is False

    def test_file_to_module(self):
        assert _file_to_module("components/Button.ts") == "components.Button"
        assert _file_to_module("src/utils/helper.js") == "src.utils.helper"
        assert _file_to_module("index.ts") == "index"
        assert _file_to_module("runner.py") == ""

    def test_is_test_file(self):
        assert _is_test_file("foo.test.ts", {}) is True
        assert _is_test_file("foo.spec.ts", {}) is True
        assert _is_test_file("foo.test.tsx", {}) is True
        assert _is_test_file("index.ts", {}) is False
        assert _is_test_file("src/app.ts", {}) is False

    def test_special_names(self):
        for n in ("constructor", "toString", "valueOf", "then", "catch",
                  "apply", "call", "bind", "get", "set", "next"):
            assert n in _TYPESCRIPT_SPECIAL_NAMES

    def test_public_api_names(self):
        assert "main" in _TYPESCRIPT_PUBLIC_API_NAMES

    def test_default_excludes(self):
        for d in ("node_modules", "dist", "build", ".next"):
            assert d in _TYPESCRIPT_DEFAULT_EXCLUDES


# =============================================================================
# Import analysis tests (unused-import detection)
# =============================================================================


@tree_sitter_available
class TestTypeScriptImports:
    def _imports(self, src: str) -> list[Any]:
        """Parse *src* and return the ImportInfo list for top-level imports."""
        from graphlint.analyzer.language.typescript.constants import _get_typescript_language
        import tree_sitter
        parser = tree_sitter.Parser()
        lang = _get_typescript_language()
        if hasattr(parser, "set_language"):
            parser.set_language(lang)
        else:
            parser.language = lang
        tree = parser.parse(src.encode("utf-8"))
        an = TSTypeScriptImportAnalyzer()
        out: list[Any] = []

        def walk(node: Any) -> None:
            if node.type == "import_statement":
                info = an.analyze_import(node)
                if info:
                    out.append(info)
            for child in node.children:
                walk(child)

        walk(tree.root_node)
        return out

    def test_default_import(self):
        infos = self._imports('import express from "express";')
        assert len(infos) == 1
        assert infos[0].module_path == "express"
        assert infos[0].default_import == "express"
        assert infos[0].imported_names == ["express"]

    def test_named_import(self):
        infos = self._imports('import { readFile } from "fs/promises";')
        assert len(infos) == 1
        assert infos[0].module_path == "fs/promises"
        assert infos[0].imported_names == ["readFile"]

    def test_named_import_with_alias(self):
        infos = self._imports('import { createServer as cs } from "net";')
        assert len(infos) == 1
        assert infos[0].imported_names == ["createServer"]
        assert infos[0].alias_map == {"createServer": "cs"}

    def test_namespace_import(self):
        infos = self._imports('import * as Net from "net";')
        assert len(infos) == 1
        assert infos[0].namespace_import == "Net"
        assert infos[0].imported_names == ["Net"]

    def test_side_effect_import_is_star(self):
        infos = self._imports('import "reflect-metadata";')
        assert len(infos) == 1
        assert infos[0].imported_names == ["*"]

    def test_type_import(self):
        infos = self._imports('import type { Options } from "types";')
        assert len(infos) == 1
        assert infos[0].is_type_import is True
        assert infos[0].imported_names == ["Options"]

    def test_detect_unused_imports(self):
        an = TSTypeScriptImportAnalyzer()
        from graphlint.analyzer.language.typescript.imports import ImportInfo

        used = {"express", "Router"}
        imports = [
            ImportInfo(module_path="express", imported_names=["express"], default_import="express"),
            ImportInfo(module_path="net", imported_names=["Router"]),
            ImportInfo(module_path="fs", imported_names=["readFile"]),
        ]
        unused = an.detect_unused_imports(imports, used, "index.ts")
        assert len(unused) == 1
        assert unused[0][1] == "'readFile' imported but not used"

    def test_detect_unused_import_skips_side_effect(self):
        an = TSTypeScriptImportAnalyzer()
        from graphlint.analyzer.language.typescript.imports import ImportInfo

        imports = [
            ImportInfo(module_path="reflect-metadata", imported_names=["*"]),
            ImportInfo(module_path="x", imported_names=["Used"]),
        ]
        unused = an.detect_unused_imports(imports, {"Used"}, "index.ts")
        assert unused == []

    def test_detect_unused_import_honours_alias(self):
        an = TSTypeScriptImportAnalyzer()
        from graphlint.analyzer.language.typescript.imports import ImportInfo

        # import { createServer as cs } — code uses `cs`, raw name is createServer.
        imports = [
            ImportInfo(module_path="net", imported_names=["createServer"],
                       alias_map={"createServer": "cs"}),
        ]
        assert an.detect_unused_imports(imports, {"cs"}, "index.ts") == []
        unused = an.detect_unused_imports(imports, {"createServer"}, "index.ts")
        assert len(unused) == 1


# =============================================================================
# Visitor / parser end-to-end
# =============================================================================


@tree_sitter_available
class TestTypeScriptParser:
    """End-to-end parsing of a real TS source file."""

    def _parse(self, src: str, rel_path: str = "index.ts"):
        import tempfile

        from graphlint.analyzer.language.typescript.parser import TSTypeScriptSourceParser

        with tempfile.TemporaryDirectory() as d:
            full = os.path.join(d, rel_path)
            os.makedirs(os.path.dirname(full) or d, exist_ok=True)
            with open(full, "w", encoding="utf-8") as fh:
                fh.write(src)
            parser = TSTypeScriptSourceParser(d, {})
            return parser.parse_file(full)

    def test_parses_nodes_and_usages(self):
        src = (
            'import { readFile } from "fs/promises";\n'
            "const usedVar = 1;\n"
            "export function main() { const x = usedVar; }\n"
        )
        result = self._parse(src)
        # unused import detected
        warns = [w for w in result.warnings if w.warn_type == "unused_import"]
        assert warns, "expected an unused_import warning for readFile"
        assert "readFile" in warns[0].message
        # named nodes present
        names = {n.name for n in result.nodes}
        assert "main" in names
        assert "usedVar" in names

    def test_alias_import_not_mistakenly_unused(self):
        src = (
            'import { createServer as cs } from "net";\n'
            "export function main() { cs(); }\n"
        )
        result = self._parse(src)
        warns = [w for w in result.warnings if w.warn_type == "unused_import"]
        assert warns == [], f"alias import used via `cs` should not be unused: {warns}"

    def test_used_import_not_reported(self):
        src = (
            'import express from "express";\n'
            "export function main() { express(); }\n"
        )
        result = self._parse(src)
        warns = [w for w in result.warnings if w.warn_type == "unused_import"]
        assert warns == []

    def test_mixed_used_and_unused(self):
        src = (
            'import { Router, readFile } from "net";\n'
            "export function main() { Router(); }\n"
        )
        result = self._parse(src)
        warns = [w for w in result.warnings if w.warn_type == "unused_import"]
        assert len(warns) == 1
        assert "readFile" in warns[0].message

    def test_side_effect_import_skipped(self):
        src = 'import "reflect-metadata";\n' "export const x = 1;\n"
        result = self._parse(src)
        warns = [w for w in result.warnings if w.warn_type == "unused_import"]
        assert warns == [], f"side-effect import should be skipped: {warns}"
