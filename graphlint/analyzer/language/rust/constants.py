# -*- coding: utf-8 -*-
"""Rust-specific constants: special names, excludes, node-type mappings, utilities."""

from __future__ import annotations

import fnmatch
import os
from typing import Any

# ---------------------------------------------------------------------------
# Tree-sitter availability
# ---------------------------------------------------------------------------

_TREE_SITTER_AVAILABLE: bool = False
try:
    import tree_sitter  # noqa: F401
    import tree_sitter_rust  # noqa: F401

    _TREE_SITTER_AVAILABLE = True
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Public API names (language-level semantics — exempt from unused warnings)
# ---------------------------------------------------------------------------

_RUST_PUBLIC_API_NAMES: frozenset[str] = frozenset(
    {
        "main",  # Binary entry point — called by the OS runtime
    }
)

# ---------------------------------------------------------------------------
# Special names — methods invoked implicitly by the Rust runtime or compiler
# ---------------------------------------------------------------------------

_RUST_SPECIAL_NAMES: frozenset[str] = frozenset(
    {
        "drop",
        "deref",
        "deref_mut",
        "index",
        "index_mut",
        "call",
        "call_mut",
        "call_once",
        "next",
        "into_iter",
        "from",
        "into",
        "branch",
        "from_residual",
        "report",
        "resume",
        "poll",
        "add",
        "sub",
        "mul",
        "div",
        "rem",
        "neg",
        "not",
        "bitand",
        "bitor",
        "bitxor",
        "shl",
        "shr",
        "add_assign",
        "sub_assign",
        "mul_assign",
        "div_assign",
        "rem_assign",
        "bitand_assign",
        "bitor_assign",
        "bitxor_assign",
        "shl_assign",
        "shr_assign",
        "eq",
        "ne",
        "partial_cmp",
        "lt",
        "le",
        "gt",
        "ge",
        "cmp",
        "fmt",
        "default",
        "clone",
        "as_ref",
        "as_mut",
        "borrow",
        "borrow_mut",
        "to_owned",
        "source",
    }
)

# ---------------------------------------------------------------------------
# Default exclude patterns
# ---------------------------------------------------------------------------

_RUST_DEFAULT_EXCLUDES: frozenset[str] = frozenset(
    {
        "target",
        ".cargo",
    }
)

# ---------------------------------------------------------------------------
# Tree-sitter CST → graphlint NodeInfo.node_type mapping
# ---------------------------------------------------------------------------

_CST_TYPE_TO_NODE_TYPE: dict[str, str] = {
    "function_item": "function",
    "struct_item": "struct",
    "enum_item": "enum",
    "union_item": "union",
    "trait_item": "trait",
    "const_item": "constant",
    "static_item": "constant",
    "type_item": "type_alias",
    "mod_item": "module",
    "macro_definition": "macro",
    "function_signature_item": "function",
}

# Node types for items that appear inside impl blocks
_IMPL_NODE_TYPES: dict[str, str] = {
    "function_item": "method",
    "const_item": "constant",
    "type_item": "type_alias",
}

# ---------------------------------------------------------------------------
# Path / naming utilities
# ---------------------------------------------------------------------------


def _file_to_module(path: str) -> str:
    """Convert a Rust source path to its module path.

    >>> _file_to_module("src/lib.rs")
    'crate'
    >>> _file_to_module("src/foo.rs")
    'crate::foo'
    >>> _file_to_module("src/foo/mod.rs")
    'crate::foo'
    >>> _file_to_module("src/foo/bar.rs")
    'crate::foo::bar'
    >>> _file_to_module("tests/integration_test.rs")
    'crate::integration_test'
    >>> _file_to_module("examples/demo.rs")
    'crate::demo'
    >>> _file_to_module("custom/lib.rs")
    'crate::custom'
    >>> _file_to_module("Cargo.toml")
    ''
    """
    if not path.endswith(".rs"):
        return ""

    path_no_ext = path[:-3]
    normalized = path_no_ext.replace("\\", "/")

    parts = normalized.split("/")

    # Strip known crate-root prefixes
    if parts and parts[0] in ("src", "tests", "examples", "benches"):
        parts = parts[1:]

    if not parts:
        return "crate"

    # Strip lib.rs / main.rs / mod.rs from the leaf
    if parts[-1] in ("mod", "lib", "main"):
        parts = parts[:-1]

    if not parts:
        return "crate"

    return "crate::" + "::".join(parts)


_RUST_TEST_DIR_PATTERNS: tuple[str, ...] = ("tests/",)
_RUST_TEST_FILE_SUFFIXES: tuple[str, ...] = ("_test.rs",)
_RUST_TEST_FILE_PREFIXES: tuple[str, ...] = ("test_",)

# Config-level overrides from shared test_patterns config,
# with Rust-appropriate defaults.
_RUST_DEFAULT_FILE_PATTERNS: tuple[str, ...] = ("test_*.rs", "*_test.rs")
_RUST_DEFAULT_DIR_PATTERNS: tuple[str, ...] = ("tests/",)


def _is_test_file(file_path: str, config: dict[str, Any]) -> bool:
    """Check whether *file_path* is a Rust test file.

    Matches ``tests/`` directory or ``*_test.rs`` / ``test_*.rs`` naming
    conventions.  ``#[test]`` attribute detection is deferred to the
    entry-point detector; this is a fast filesystem-level pre-filter.
    """
    test_patterns = config.get("test_patterns", {})
    file_patterns = test_patterns.get("file_patterns", list(_RUST_DEFAULT_FILE_PATTERNS))
    dir_patterns = test_patterns.get("dir_patterns", list(_RUST_DEFAULT_DIR_PATTERNS))

    normalized = file_path.replace("\\", "/")
    basename = os.path.basename(file_path)
    dirname = os.path.dirname(file_path).replace(os.sep, "/")

    # Rust-native: integration tests are always under tests/
    for d in _RUST_TEST_DIR_PATTERNS:
        if normalized == d.rstrip("/") or normalized.startswith(d):
            return True

    # Rust-native: *_test.rs convention
    for suffix in _RUST_TEST_FILE_SUFFIXES:
        if normalized.endswith(suffix):
            return True

    # Rust-native: test_* convention
    for prefix in _RUST_TEST_FILE_PREFIXES:
        if basename.startswith(prefix):
            return True

    # Config-level patterns (enables user overrides for mono-repos)
    dir_with_slash = dirname + "/"
    if any(
        fnmatch.fnmatch(dir_with_slash, d) or dir_with_slash.startswith(d)
        for d in dir_patterns
    ):
        return True

    if any(fnmatch.fnmatch(basename, p) for p in file_patterns):
        return True

    return False


# ---------------------------------------------------------------------------
# Tree-sitter Language singleton (lazy, per-process)
# ---------------------------------------------------------------------------

_RUST_LANG: Any = None


def _get_rust_language() -> Any:
    """Return the tree-sitter Language for Rust (lazy singleton per process)."""
    global _RUST_LANG
    if _RUST_LANG is None:
        if not _TREE_SITTER_AVAILABLE:
            raise ImportError(
                "tree-sitter-rust is not installed. "
                "Install with: pip install graphlint[rust]"
            )
        import tree_sitter
        import tree_sitter_rust

        _RUST_LANG = tree_sitter.Language(tree_sitter_rust.language())
    return _RUST_LANG
