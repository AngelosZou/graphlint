# -*- coding: utf-8 -*-
"""Tests for C# ``using`` directive analysis and unused-import detection.

These cover the alias-parsing fix in :meth:`CSharpImportAnalyzer.analyze_using`
(the tree-sitter-c-sharp grammar uses an ``=`` operator child, not a
``name_equals`` node) and the end-to-end ``unused_import`` warning path wired
through :class:`CSharpSourceParser`.
"""

from __future__ import annotations

import os
import tempfile

import pytest

from graphlint.analyzer.language.csharp.constants import _TREE_SITTER_CSHARP_AVAILABLE
from graphlint.analyzer.language.csharp.imports import CSharpImportAnalyzer

tree_sitter_available = pytest.mark.skipif(
    not _TREE_SITTER_CSHARP_AVAILABLE, reason="tree-sitter-c-sharp not installed"
)


def _parse_source(source: str):
    """Parse C# *source* and return the resulting ParseResult."""
    import tree_sitter
    from graphlint.analyzer.language.csharp.constants import _get_csharp_language
    from graphlint.analyzer.language.csharp.parser import CSharpSourceParser

    parser = tree_sitter.Parser()
    lang = _get_csharp_language()
    if hasattr(parser, "set_language"):
        parser.set_language(lang)
    else:
        parser.language = lang
    tree = parser.parse(bytes(source, "utf-8"))

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "Probe.cs")
        with open(path, "w", encoding="utf-8") as f:
            f.write(source)
        src = CSharpSourceParser(root_dir=tmp, config={})
        return src.parse_file(path)


# =============================================================================
# analyze_using — directive parsing
# =============================================================================


@tree_sitter_available
class TestAnalyzeUsing:
    def _analyze_line(self, line: str):
        import tree_sitter
        from graphlint.analyzer.language.csharp.constants import _get_csharp_language

        parser = tree_sitter.Parser()
        lang = _get_csharp_language()
        if hasattr(parser, "set_language"):
            parser.set_language(lang)
        else:
            parser.language = lang
        tree = parser.parse(bytes(line, "utf-8"))
        node = next(
            (n for n in tree.root_node.children if n.type == "using_directive"), None
        )
        assert node is not None, f"no using_directive found in {line!r}"
        return CSharpImportAnalyzer().analyze_using(node)

    def test_namespace_using_is_wildcard(self):
        info = self._analyze_line("using System;\n")
        assert info.module_path == "System"
        assert info.imported_names == ["*"]  # conservative, cannot resolve namespace
        assert info.is_static is False

    def test_qualified_namespace_using(self):
        info = self._analyze_line("using System.Collections.Generic;\n")
        assert info.module_path == "System.Collections.Generic"
        assert info.imported_names == ["*"]

    def test_alias_using_parses_alias_name(self):
        # Regression for the alias bug: tree-sitter-c-sharp has no name_equals
        # node — the alias is the identifier and the target is the qualified_name.
        info = self._analyze_line("using Timer = System.Timers.Timer;\n")
        assert info.module_path == "System.Timers.Timer"   # real module path
        assert info.imported_names == ["Timer"]            # the alias name
        assert info.alias_map == {"Timer": "System.Timers.Timer"}

    def test_static_using_is_wildcard(self):
        info = self._analyze_line("using static System.Math;\n")
        assert info.module_path == "System.Math"
        assert info.imported_names == ["*"]
        assert info.is_static is True

    def test_global_using(self):
        info = self._analyze_line("global using System;\n")
        assert info.module_path == "System"


# =============================================================================
# detect_unused_imports — reporting logic
# =============================================================================


class TestDetectUnusedImports:
    def _make(self, module, names, stat=False):
        from graphlint.analyzer.language.csharp.imports import UseInfo

        return UseInfo(module_path=module, imported_names=names, is_static=stat)

    def test_reports_unused_alias(self):
        unused = CSharpImportAnalyzer().detect_unused_imports(
            [self._make("System.Text.RegularExpressions.Regex", ["Regex"])],
            {"Calculator"},
            "/test.cs",
        )
        assert len(unused) == 1
        assert "Regex" in unused[0][1]

    def test_skips_wildcard_imports(self):
        unused = CSharpImportAnalyzer().detect_unused_imports(
            [self._make("System", ["*"]), self._make("System.Math", ["*"], stat=True)],
            set(),
            "/test.cs",
        )
        assert unused == []  # cannot determine namespace usage, never flagged

    def test_used_alias_not_reported(self):
        unused = CSharpImportAnalyzer().detect_unused_imports(
            [self._make("System.Timers.Timer", ["Timer"])],
            {"Timer"},  # Timer appears in code
            "/test.cs",
        )
        assert unused == []

    def test_empty_imports(self):
        assert CSharpImportAnalyzer().detect_unused_imports([], set(), "/test.cs") == []


# =============================================================================
# End-to-end: parse + unused-import warning
# =============================================================================


@tree_sitter_available
class TestUnusedImportEndToEnd:
    def _warn_types(self, source: str):
        return [w.warn_type for w in _parse_source(source).warnings]

    def test_unused_alias_emits_warning(self):
        source = """\
using System;
using Timer = System.Timers.Timer;
using Regex = System.Text.RegularExpressions.Regex;

class Calculator
{
    static Timer _t = new Timer(1000);
    public int Add(int a, int b) => a + b;
}
"""
        warns = self._warn_types(source)
        assert "unused_import" in warns  # Regex alias is unused

    def test_used_alias_no_warning(self):
        source = """\
using Timer = System.Timers.Timer;

class Clock
{
    static Timer _t = new Timer(1000);
}
"""
        warns = self._warn_types(source)
        assert "unused_import" not in warns

    def test_namespace_using_no_warning(self):
        source = """\
using System;

class Program
{
    static void Main() { System.Console.WriteLine("hi"); }
}
"""
        warns = self._warn_types(source)
        assert "unused_import" not in warns  # namespace using is never flagged

    def test_only_unused_alias_warned_among_used(self):
        source = """\
using Timer = System.Timers.Timer;
using Regex = System.Text.RegularExpressions.Regex;

class Clock
{
    static Timer _t = new Timer(1000);
}
"""
        warns = self._warn_types(source)
        # Exactly one unused_import (Regex), and its message names Regex.
        unused_msgs = [w.message for w in _parse_source(source).warnings if w.warn_type == "unused_import"]
        assert len(unused_msgs) == 1
        assert "Regex" in unused_msgs[0]
        assert "Timer" not in unused_msgs[0]
