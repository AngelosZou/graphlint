# -*- coding: utf-8 -*-
"""Tests for the TypeScript/JavaScript language adapter."""

from __future__ import annotations

import fnmatch
import os
from typing import Any

import pytest

from graphlint.config.defaults import DEFAULT_CONFIG
from graphlint.analyzer.language.typescript.constants import (
    _REACT_LIFECYCLE_NAMES,
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

    def test_is_test_file_any_depth(self):
        # Jest/Vitest conventions must match at ANY depth, not just root.
        assert _is_test_file("src/__tests__/foo.ts", {}) is True
        assert _is_test_file("src/__tests__/foo.test.ts", {}) is True
        assert _is_test_file("src/__test__/foo.ts", {}) is True
        assert _is_test_file("components/Button.test.tsx", {}) is True
        assert _is_test_file("deep/nested/spec/helper.spec.js", {}) is True
        assert _is_test_file("src/app.ts", {}) is False

    def test_entry_file_pattern_excludes_other_languages(self):
        ts_rules = {
            r["name"]: r
            for r in DEFAULT_CONFIG["entry_rules"]
            if r.get("name", "").startswith("typescript_")
        }
        assert set(ts_rules) == {
            "typescript_main", "typescript_index", "typescript_cli",
            "typescript_nextjs", "typescript_nestjs",
            "typescript_react_component", "typescript_test",
        }

        globbed = [
            name for name, r in ts_rules.items()
            if r["file_pattern"] == "**/*.*[tjs][sx]"
        ]
        assert len(globbed) == 6

        for name in globbed:
            pattern = ts_rules[name]["file_pattern"]
            for ext in (".ts", ".tsx", ".js", ".jsx", ".mts", ".cts", ".mjs", ".cjs"):
                assert fnmatch.fnmatch(f"src/app{ext}", pattern), (
                    f"{name} pattern {pattern!r} must match {ext}"
                )
            for bad in (".py", ".rs", ".cs", ".sh"):
                assert not fnmatch.fnmatch(f"src/app{bad}", pattern), (
                    f"{name} pattern {pattern!r} must not match .{bad}"
                )

        assert ts_rules["typescript_nextjs"]["file_pattern"] == "**pages/*.*[tjs][sx]"
        nextjs = ts_rules["typescript_nextjs"]["file_pattern"]
        for p in ("pages/index.ts", "src/pages/app.tsx", "pages/deep/nested/a.ts"):
            assert fnmatch.fnmatch(p, nextjs), f"nextjs pattern must match {p}"
        for p in ("app/pages/views.py", "pages/main.rs", "pages/Program.cs"):
            assert not fnmatch.fnmatch(p, nextjs), (
                f"nextjs pattern must not leak into {p}"
            )

    def test_special_names(self):
        preserved = (
            "constructor", "toString", "valueOf", "toJSON",
            "Symbol.iterator", "Symbol.asyncIterator",
            "Symbol.toPrimitive", "Symbol.toStringTag",
        )
        for n in preserved:
            assert n in _TYPESCRIPT_SPECIAL_NAMES
        # React lifecycle methods are runtime-invoked and must never be dead.
        assert _REACT_LIFECYCLE_NAMES <= _TYPESCRIPT_SPECIAL_NAMES
        removed = (
            "get", "set", "apply", "call", "bind", "then", "catch",
            "finally", "next", "return", "throw",
        )
        for n in removed:
            assert n not in _TYPESCRIPT_SPECIAL_NAMES

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

    def test_type_position_usage_not_unused(self):
        # Type annotation, extends clause, and type-only imports must register
        # usage (or be skipped) so they are never reported unused.
        src = (
            'import { User } from "./user";\n'
            'import { Base } from "./base";\n'
            'import type { Options } from "./types";\n'
            "const u: User = null;\n"
            "export class X extends Base {}\n"
        )
        result = self._parse(src)
        warns = [w for w in result.warnings if w.warn_type == "unused_import"]
        assert warns == [], f"type-position usage should not be unused: {warns}"

    def test_default_and_namespace_imports_not_unused(self):
        src = (
            'import express from "express";\n'
            'import * as Net from "net";\n'
            "export function main() { express(); Net.connect(); }\n"
        )
        result = self._parse(src)
        warns = [w for w in result.warnings if w.warn_type == "unused_import"]
        assert warns == [], f"default/namespace import should not be unused: {warns}"

    def test_genuinely_unused_default_import_still_flagged(self):
        src = 'import express from "express";\n' "export const x = 1;\n"
        result = self._parse(src)
        warns = [w for w in result.warnings if w.warn_type == "unused_import"]
        assert warns and "express" in warns[0].message

    def test_public_as_entry_only_exported(self):
        from graphlint.analyzer.language.typescript.entry import TSEntryPointDetector

        src = (
            "export function main() {}\n"
            "function helper() {}\n"
            "export const pub = 1;\n"
        )
        result = self._parse(src)
        detector = TSEntryPointDetector({"_public_as_entry": True, "entry_rules": []})
        entries = detector.detect({result.file_path: result}, result.nodes, {})
        node_names = {n.id: n.name for n in result.nodes}
        entry_names = {node_names[e.node_id] for e in entries}
        assert "main" in entry_names
        assert "pub" in entry_names
        assert "helper" not in entry_names


# =============================================================================
# Regressions — cross-language rule leaks, double-walks, JSX/test rules,
# phantom usages
# =============================================================================


@tree_sitter_available
class TestTypeScriptRegressions:
    """Regression tests for reported TS backend bugs."""

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

    def _detector(self, rule_names: list[str]):
        from graphlint.config.defaults import DEFAULT_CONFIG
        from graphlint.analyzer.language.typescript.entry import TSEntryPointDetector

        det = TSEntryPointDetector(DEFAULT_CONFIG)
        det._rules = [
            r for r in DEFAULT_CONFIG["entry_rules"] if r["name"] in rule_names
        ]
        return det

    def test_export_default_declaration_walked_once(self):
        src = (
            "export default class Page {\n"
            "  render() { return 1; }\n"
            "  other() { return 2; }\n"
            "}\n"
        )
        result = self._parse(src, "page.ts")
        assert len([n for n in result.nodes if n.name == "Page"]) == 1
        names = {n.name for n in result.nodes}
        assert {"render", "other"} <= names

    def test_export_default_function_walked_once(self):
        result = self._parse("export default function App() { return 1; }\n", "app.ts")
        assert len([n for n in result.nodes if n.name == "App"]) == 1

    def test_jsx_emits_jsx_element_edge_and_react_rule_fires(self):
        src = (
            "export default function App() {\n"
            "  return <Button label='ok' />;\n"
            "}\n"
        )
        result = self._parse(src, "App.tsx")
        jsx = [r for r in result.references if r.edge_type == "jsx_element"]
        assert any(r.target_name == "Button" for r in jsx)
        entries = self._detector(["typescript_react_component"]).detect(
            {result.file_path: result}, result.nodes, {}
        )
        assert entries, "typescript_react_component must fire on JSX"

    def test_nextjs_rule_matches_root_level_pages(self):
        result = self._parse("export default function P() {}\n", "pages/index.ts")
        entries = self._detector(["typescript_nextjs"]).detect(
            {result.file_path: result}, result.nodes, {}
        )
        assert entries, "root-level pages/index.ts must be a Next.js entry"

    def test_index_rule_matches_jsx_cts_cjs_and_root(self):
        for rel in ("src/index.jsx", "src/index.cts", "src/index.cjs", "index.ts"):
            result = self._parse("export const a = 1;\n", rel)
            entries = self._detector(["typescript_index"]).detect(
                {result.file_path: result}, result.nodes, {}
            )
            assert entries, f"{rel} must match typescript_index"

    def test_jest_describe_it_calls_are_test_entries(self):
        src = (
            "describe('sum', () => {\n"
            "  it('adds', () => {});\n"
            "});\n"
        )
        result = self._parse(src, "sum.test.ts")
        entries = self._detector(["typescript_test"]).detect(
            {result.file_path: result}, result.nodes, {}
        )
        assert entries, "Jest describe/it calls must satisfy _check_test_file"

    def test_export_alias_and_namespace_no_phantom_usages(self):
        src = (
            "const a = 1;\n"
            "export { a as b };\n"
            "export * as ns from './x';\n"
        )
        result = self._parse(src, "exp.ts")
        reads = [r.target_name for r in result.references if r.edge_type == "read"]
        # The re-export source name is a genuine use; the alias and the
        # namespace name are new export names — phantom usages.
        assert "a" in reads
        assert "b" not in reads
        assert "ns" not in reads
        assert "b" not in result.name_usages
        assert "ns" not in result.name_usages

    def test_destructuring_declares_real_bindings_only(self):
        src = (
            "const obj = { a: 2 };\n"
            "const { a: b } = obj;\n"
            "const { c, d = 1 } = obj;\n"
            "const [x, y] = obj;\n"
        )
        result = self._parse(src, "destr.ts")
        names = {n.name for n in result.nodes}
        assert {"b", "c", "d", "x", "y"} <= names
        # No raw pattern text nodes, no phantom usage of declared bindings.
        assert "{ a: b }" not in names
        assert "{ c, d = 1 }" not in names
        assert "[x, y]" not in names
        assert "b" not in result.name_usages
        assert "c" not in result.name_usages
        assert "x" not in result.name_usages
