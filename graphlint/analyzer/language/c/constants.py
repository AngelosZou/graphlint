# -*- coding: utf-8 -*-
"""C-specific constants: file utilities, test detection, tree-sitter loader."""

from __future__ import annotations

import fnmatch
import os
from typing import Any

# ---------------------------------------------------------------------------
# Tree-sitter availability
# ---------------------------------------------------------------------------

_TREE_SITTER_C_AVAILABLE: bool = False
try:
    import tree_sitter  # noqa: F401
    import tree_sitter_c  # noqa: F401

    _TREE_SITTER_C_AVAILABLE = True
except ImportError:
    pass


# ---------------------------------------------------------------------------
# Public API names (language-level semantics)
# ---------------------------------------------------------------------------

_C_PUBLIC_API_NAMES: frozenset[str] = frozenset(
    {
        "main",
    }
)


_C_SPECIAL_NAMES: frozenset[str] = frozenset(
    {
        "main",
    }
)


# ---------------------------------------------------------------------------
# Default exclude patterns
# ---------------------------------------------------------------------------

_C_DEFAULT_EXCLUDES: frozenset[str] = frozenset(
    {
        "build",
        "dist",
        ".cache",
        "node_modules",
        ".git",
        ".svn",
        ".hg",
        ".idea",
        ".vscode",
        ".vs",
        ".graphlint",
        "*.o",
        "*.so",
        "*.a",
        "*.dylib",
        "*.dll",
        "*.exe",
        "*.out",
    }
)

# ---------------------------------------------------------------------------
# Tree-sitter CST -> graphlint NodeInfo.node_type mapping
# ---------------------------------------------------------------------------

_CST_TYPE_TO_NODE_TYPE: dict[str, str] = {
    "function_definition": "function",
    "preproc_def": "macro",
    "preproc_function_def": "macro",
    "type_definition": "type",
    "struct_specifier": "struct",
    "enum_specifier": "enum",
    "union_specifier": "union",
}

# ---------------------------------------------------------------------------
# Path / naming utilities
# ---------------------------------------------------------------------------


def _file_to_module(path: str) -> str:
    """Convert a C source path to its module name.

    >>> _file_to_module("src/main.c")
    'src.main'
    >>> _file_to_module("lib/util.h")
    'lib.util'
    """
    if not (path.endswith(".c") or path.endswith(".h")):
        return ""

    path_no_ext = path[:-2] if path.endswith((".c", ".h")) else path
    normalized = path_no_ext.replace("\\", "/")
    parts = [p for p in normalized.split("/") if p]
    return ".".join(parts)


# ---------------------------------------------------------------------------
# Test file detection
# ---------------------------------------------------------------------------

_C_TEST_FILE_SUFFIXES: tuple[str, ...] = ("_test.c", "test.c", "_test.h", "test.h")
_C_TEST_FILE_PREFIXES: tuple[str, ...] = ("test_",)


def _is_test_file(file_path: str, config: dict[str, Any]) -> bool:
    """Check whether *file_path* is a C test file."""
    normalized = file_path.replace("\\", "/")
    basename = os.path.basename(file_path)

    for prefix in _C_TEST_FILE_PREFIXES:
        if basename.startswith(prefix):
            return True

    for suffix in _C_TEST_FILE_SUFFIXES:
        if basename.endswith(suffix):
            return True

    test_patterns = config.get("test_patterns", {})
    file_patterns = test_patterns.get("file_patterns", [])
    dir_patterns = test_patterns.get("dir_patterns", [])

    dirname = os.path.dirname(file_path).replace(os.sep, "/")
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

_C_LANG: Any = None


def _get_c_language() -> Any:
    """Return the tree-sitter Language for C (lazy singleton per process)."""
    global _C_LANG
    if _C_LANG is None:
        if not _TREE_SITTER_C_AVAILABLE:
            raise ImportError(
                "tree-sitter-c is not installed. "
                "Install with: pip install graphlint[c]"
            )
        import tree_sitter
        import tree_sitter_c

        _C_LANG = tree_sitter.Language(tree_sitter_c.language())
    return _C_LANG
