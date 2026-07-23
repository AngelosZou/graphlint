# -*- coding: utf-8 -*-
"""Unit tests for Rust language adapter utilities (no tree-sitter required)."""

from __future__ import annotations

import pytest

from graphlint.analyzer.language.rust.constants import (
    _RUST_DEFAULT_EXCLUDES,
    _RUST_PUBLIC_API_NAMES,
    _RUST_SPECIAL_NAMES,
    _file_to_module,
    _is_test_file,
)
from graphlint.analyzer.language.rust.imports import (
    RustImportAnalyzer,
    UseInfo,
)


class TestFileToModule:
    """Path → module-qname conversion."""

    def test_lib_rs_is_crate(self):
        assert _file_to_module("src/lib.rs") == "crate"

    def test_main_rs_is_crate(self):
        assert _file_to_module("src/main.rs") == "crate"

    def test_mod_file_is_submodule(self):
        assert _file_to_module("src/foo.rs") == "crate::foo"

    def test_nested_mod_file(self):
        assert _file_to_module("src/foo/bar.rs") == "crate::foo::bar"

    def test_mod_rs_is_directory_module(self):
        assert _file_to_module("src/foo/mod.rs") == "crate::foo"

    def test_nested_mod_rs(self):
        assert _file_to_module("src/foo/bar/mod.rs") == "crate::foo::bar"

    def test_tests_dir(self):
        assert _file_to_module("tests/integration_test.rs") == "crate::integration_test"

    def test_examples_dir(self):
        assert _file_to_module("examples/demo.rs") == "crate::demo"

    def test_benches_dir(self):
        assert _file_to_module("benches/benchmark.rs") == "crate::benchmark"

    def test_non_rs_returns_empty(self):
        assert _file_to_module("Cargo.toml") == ""

    def test_windows_backslash(self):
        assert _file_to_module("src\\foo\\bar.rs") == "crate::foo::bar"


class TestIsTestFile:
    def test_tests_directory(self):
        assert _is_test_file("tests/integration_test.rs", {}) is True

    def test_test_suffix(self):
        assert _is_test_file("src/foo_test.rs", {}) is True

    def test_test_prefix(self):
        assert _is_test_file("src/test_foo.rs", {}) is True

    def test_non_test_file(self):
        assert _is_test_file("src/main.rs", {}) is False

    def test_non_test_dir_no_suffix_match(self):
        """A file in a non-tests directory without _test suffix is NOT a test file."""
        assert _is_test_file("benchmarks/perf_runner.rs", {}) is False

    def test_tests_directory_exact(self):
        """The 'tests' directory without trailing slash should match."""
        assert _is_test_file("tests.rs", {}) is False

    def test_tests_subdirectory_module(self):
        """A module file in tests/ should be detected."""
        assert _is_test_file("tests/common/mod.rs", {}) is True

    def test_no_conftest_equivalent(self):
        """Rust has no conftest.py equivalent — config_files is ignored."""
        config = {"test_patterns": {"config_files": ["conftest.py"]}}
        assert _is_test_file("src/main.rs", config) is False

    def test_config_test_patterns(self):
        config = {
            "test_patterns": {
                "file_patterns": ["spec_*.rs"],
                "dir_patterns": ["specs/"],
            }
        }
        assert _is_test_file("src/my_file.rs", config) is False
        assert _is_test_file("specs/runner_test.rs", config) is True
        assert _is_test_file("src/spec_builder.rs", config) is True
        assert _is_test_file("tests/integration.rs", config) is True

    def test_default_fallbacks_are_rust_patterns(self):
        """Without config, Rust defaults (test_*.rs, *_test.rs) are used, not Python ones."""
        from graphlint.analyzer.language.rust.constants import (
            _RUST_DEFAULT_FILE_PATTERNS,
            _RUST_DEFAULT_DIR_PATTERNS,
        )
        assert _RUST_DEFAULT_FILE_PATTERNS == ("test_*.rs", "*_test.rs")
        assert _RUST_DEFAULT_DIR_PATTERNS == ("tests/",)
        assert "conftest.py" not in str(_RUST_DEFAULT_FILE_PATTERNS)


class TestConstants:
    def test_main_is_public_api(self):
        assert "main" in _RUST_PUBLIC_API_NAMES

    def test_drop_is_special(self):
        assert "drop" in _RUST_SPECIAL_NAMES

    def test_deref_is_special(self):
        assert "deref" in _RUST_SPECIAL_NAMES

    def test_operator_overloads_are_special(self):
        for op in ("add", "sub", "mul", "div"):
            assert op in _RUST_SPECIAL_NAMES

    def test_target_is_excluded(self):
        assert "target" in _RUST_DEFAULT_EXCLUDES

    def test_cargo_is_excluded(self):
        assert ".cargo" in _RUST_DEFAULT_EXCLUDES

    def test_no_duplicate_special_names(self):
        """Each special name must appear exactly once — no copy-paste duplicates."""
        names = list(_RUST_SPECIAL_NAMES)
        assert len(names) == len(set(names)), (
            f"Duplicates found: {sorted(n for n in names if names.count(n) > 1)}"
        )

    def test_no_python_dunders_in_special_names(self):
        """Rust special names must not contain Python dunder patterns."""
        for name in _RUST_SPECIAL_NAMES:
            assert not name.startswith("__"), f"Python dunder leaked: {name}"

    def test_no_python_dunders_in_public_api(self):
        """Rust public API names must not contain Python dunder patterns."""
        for name in _RUST_PUBLIC_API_NAMES:
            assert not name.startswith("__"), f"Python dunder leaked: {name}"


class TestRustImportAnalyzerBasics:
    """Test UseInfo dataclass and analyzer structure."""

    def test_use_info_defaults(self):
        ui = UseInfo()
        assert ui.line == 0
        assert ui.full_path == ""
        assert ui.imported_names == []
        assert ui.is_used is False

    def test_analyzer_creation(self):
        a = RustImportAnalyzer()
        assert a is not None

    def test_detect_unused_imports_empty(self):
        a = RustImportAnalyzer()
        unused = a.detect_unused_imports([], set(), "test.rs")
        assert unused == []

    def test_detect_unused_imports_used(self):
        a = RustImportAnalyzer()
        ui = UseInfo(full_path="std::collections::HashMap", imported_names=["HashMap"])
        unused = a.detect_unused_imports([ui], {"HashMap"}, "test.rs")
        assert unused == []

    def test_detect_unused_imports_unused(self):
        a = RustImportAnalyzer()
        ui = UseInfo(full_path="std::collections::HashMap", imported_names=["HashMap"])
        unused = a.detect_unused_imports([ui], set(), "test.rs")
        assert len(unused) == 1
        assert "Unused" in unused[0][1]

    def test_detect_unused_with_alias(self):
        a = RustImportAnalyzer()
        ui = UseInfo(
            full_path="std::io",
            imported_names=["IoResult"],
            alias_map={"IoResult": "Result"},
        )
        unused = a.detect_unused_imports([ui], set(), "test.rs")
        assert len(unused) == 1

    def test_alias_name_is_used(self):
        a = RustImportAnalyzer()
        ui = UseInfo(
            full_path="std::io",
            imported_names=["IoResult"],
            alias_map={"IoResult": "Result"},
        )
        unused = a.detect_unused_imports([ui], {"Result"}, "test.rs")
        assert unused == []
