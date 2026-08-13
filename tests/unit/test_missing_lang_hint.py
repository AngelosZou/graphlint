# -*- coding: utf-8 -*-
"""Tests for silent optional-language registration and targeted hints.

Registration is silent; a hint is printed once per language to stderr
only when the project contains source files for a missing language.
"""

from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path

import pytest

from graphlint.analyzer.language.rust.constants import _TREE_SITTER_AVAILABLE

_NEEDS_RUST = pytest.mark.skipif(
    _TREE_SITTER_AVAILABLE,
    reason="tree-sitter installed — Rust adapter is registered",
)


def _python_only_registry():
    """A Python-only registry (environment-independent)."""
    from graphlint.analyzer.language.python import PythonAdapter
    from graphlint.analyzer.language.registry import LanguageRegistry

    registry = LanguageRegistry()
    registry.register(PythonAdapter())
    return registry


@pytest.fixture
def proj_dir() -> str:
    """A throw-away project root inside the workspace (auto-cleaned)."""
    root = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        ".hint_test_" + uuid.uuid4().hex[:8],
    )
    os.makedirs(root)
    yield root
    shutil.rmtree(root, ignore_errors=True)


@pytest.mark.timeout(30)
class TestSilentRegistration:
    """_build_registry must not print when optional deps are missing."""

    def test_build_registry_silent_without_optional_langs(self, capsys):
        from graphlint.api import _build_registry

        registry = _build_registry()
        out, err = capsys.readouterr()
        assert out == ""
        assert err == ""
        assert registry.adapter_for_file("x.py") is not None

    def test_build_registry_missing_optional_adapters(self):
        from graphlint.api import _build_registry

        registry = _build_registry()
        if _TREE_SITTER_AVAILABLE:
            assert registry.adapter_for_file("x.rs") is not None
        else:
            assert registry.adapter_for_file("x.rs") is None


@pytest.mark.timeout(30)
class TestMissingLangHint:
    """Hints only fire for present-but-unhandled files."""

    @pytest.fixture(autouse=True)
    def _reset_reported(self):
        """Reset per-process hint state between tests."""
        from graphlint import api

        saved = api._reported_missing_langs
        api._reported_missing_langs = set()
        try:
            yield
        finally:
            api._reported_missing_langs = saved

    def test_pure_python_project_is_silent(self, proj_dir: str, capsys):
        from graphlint.api import _build_registry, _warn_missing_lang_support

        Path(proj_dir, "main.py").write_text("print('hi')", encoding="utf-8")
        registry = _build_registry()
        _warn_missing_lang_support(proj_dir, registry)
        out, err = capsys.readouterr()
        assert out == ""
        assert err == ""

    @_NEEDS_RUST
    def test_rust_file_without_support_hints_to_stderr(self, proj_dir: str, capsys):
        from graphlint.api import _build_registry, _warn_missing_lang_support

        Path(proj_dir, "main.rs").write_text("fn main() {}", encoding="utf-8")
        registry = _build_registry()
        _warn_missing_lang_support(proj_dir, registry)
        out, err = capsys.readouterr()
        assert out == "", "stdout must stay clean"
        assert "Rust" in err
        assert "graphlint[rust]" in err

    @_NEEDS_RUST
    def test_hint_only_once_per_process(self, proj_dir: str, capsys):
        from graphlint.api import _build_registry, _warn_missing_lang_support

        Path(proj_dir, "main.rs").write_text("fn main() {}", encoding="utf-8")
        registry = _build_registry()
        _warn_missing_lang_support(proj_dir, registry)
        _warn_missing_lang_support(proj_dir, registry)
        out, err = capsys.readouterr()
        assert err.count("graphlint[rust]") == 1

    def test_excluded_dirs_are_not_counted(self, proj_dir: str, capsys):
        from graphlint.api import _build_registry, _warn_missing_lang_support

        # Dot-dirs are pruned (same rules as scan_files).
        Path(proj_dir, ".venv").mkdir()
        Path(proj_dir, ".venv", "main.rs").write_text(
            "fn main() {}", encoding="utf-8"
        )
        registry = _build_registry()
        _warn_missing_lang_support(proj_dir, registry)
        out, err = capsys.readouterr()
        assert err == ""

    def test_csharp_hint_independent(self, proj_dir: str, capsys):
        """Environment-independent: only C# files → only the C# hint."""
        from graphlint.api import _warn_missing_lang_support

        Path(proj_dir, "Program.cs").write_text(
            "class Program { static void Main() {} }", encoding="utf-8"
        )
        registry = _python_only_registry()
        _warn_missing_lang_support(proj_dir, registry)
        out, err = capsys.readouterr()
        assert out == ""
        assert "graphlint[csharp]" in err
        assert "graphlint[rust]" not in err

    def test_both_languages_hint_together(self, proj_dir: str, capsys):
        """Environment-independent: .rs + .cs files → both hints."""
        from graphlint.api import _warn_missing_lang_support

        Path(proj_dir, "main.rs").write_text("fn main() {}", encoding="utf-8")
        Path(proj_dir, "lib").mkdir()
        Path(proj_dir, "lib", "util.rs").write_text("pub fn f() {}", encoding="utf-8")
        Path(proj_dir, "Program.cs").write_text(
            "class Program { static void Main() {} }", encoding="utf-8"
        )
        registry = _python_only_registry()
        _warn_missing_lang_support(proj_dir, registry)
        out, err = capsys.readouterr()
        assert out == ""
        assert "graphlint[rust]" in err
        assert "2 .rs file(s)" in err
        assert "graphlint[csharp]" in err
