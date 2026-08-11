# -*- coding: utf-8 -*-
"""C++-specific constants: special names, excludes, node-type mappings,
utilities."""

from __future__ import annotations

import fnmatch
import os
from typing import Any

# ---------------------------------------------------------------------------
# Tree-sitter availability
# ---------------------------------------------------------------------------

_TREE_SITTER_CPP_AVAILABLE: bool = False
try:
    import tree_sitter  # noqa: F401
    import tree_sitter_cpp  # noqa: F401

    _TREE_SITTER_CPP_AVAILABLE = True
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Public API names (language-level semantics — exempt from unused warnings)
# ---------------------------------------------------------------------------

_CPP_PUBLIC_API_NAMES: frozenset[str] = frozenset(
    {
        "main",
    }
)

# ---------------------------------------------------------------------------
# Special names — methods invoked implicitly by the C++ compiler or runtime
# ---------------------------------------------------------------------------

_CPP_SPECIAL_NAMES: frozenset[str] = frozenset(
    {
        # Constructors
        "CLASS_NAME",
        # Destructor (called on scope exit / delete)
        "~CLASS_NAME",
        # Copy / move constructors & assignment
        "operator=",
        # Call operator (operator())
        "operator()",
    }
)

# ---------------------------------------------------------------------------
# Default exclude patterns
# ---------------------------------------------------------------------------

_CPP_DEFAULT_EXCLUDES: frozenset[str] = frozenset(
    {
        "build",
        "cmake-build-debug",
        "cmake-build-release",
        "node_modules",
        ".idea",
        ".vscode",
    }
)

# ---------------------------------------------------------------------------
# Tree-sitter CST → graphlint NodeInfo.node_type mapping
# ---------------------------------------------------------------------------

_CST_TYPE_TO_NODE_TYPE: dict[str, str] = {
    "class_specifier": "class",
    "struct_specifier": "struct",
    "enum_specifier": "enum",
    "union_specifier": "union",
    "using_declaration": "type",
}

# Node types for items that appear inside type declarations
_TYPE_MEMBER_NODE_TYPES: dict[str, str] = {
    "function_definition": "method",
    "field_declaration": "field",
}

# ---------------------------------------------------------------------------
# Path / naming utilities
# ---------------------------------------------------------------------------

_CPP_EXTENSIONS: frozenset[str] = frozenset({".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx"})


def _file_to_module(path: str) -> str:
    """Convert a C++ source path to its namespace-qualified name.

    >>> _file_to_module("src/Player.cpp")
    'src.Player'
    """
    for ext in sorted(_CPP_EXTENSIONS, key=len, reverse=True):
        if path.endswith(ext):
            path_no_ext = path[:-len(ext)]
            break
    else:
        return ""

    normalized = path_no_ext.replace("\\", "/")
    parts = [p for p in normalized.split("/") if p]
    return ".".join(parts)


# ---------------------------------------------------------------------------
# Test file detection
# ---------------------------------------------------------------------------

_CPP_TEST_FILE_SUFFIXES: tuple[str, ...] = ("_test", "_tests", "test_", "Test.")
_CPP_DEFAULT_FILE_PATTERNS: tuple[str, ...] = (
    "*_test.cpp", "*_test.cc", "*_test.cxx",
    "*_test.hpp", "*_test.hh", "*_test.hxx",
    "*_tests.cpp", "*_tests.cc", "*_tests.cxx",
    "test_*.cpp", "test_*.cc", "test_*.cxx",
)
_CPP_DEFAULT_DIR_PATTERNS: tuple[str, ...] = ("tests/", "test/", "Tests/", "Test/")


def _is_test_file(file_path: str, config: dict[str, Any]) -> bool:
    """Check whether *file_path* is a C++ test file."""
    test_patterns = config.get("test_patterns", {})
    file_patterns = test_patterns.get("file_patterns", list(_CPP_DEFAULT_FILE_PATTERNS))
    dir_patterns = test_patterns.get("dir_patterns", list(_CPP_DEFAULT_DIR_PATTERNS))

    normalized = file_path.replace("\\", "/")
    basename = os.path.basename(file_path)
    dirname = os.path.dirname(file_path).replace(os.sep, "/")

    for d in _CPP_DEFAULT_DIR_PATTERNS:
        if normalized == d.rstrip("/") or normalized.startswith(d):
            return True

    for suffix in _CPP_TEST_FILE_SUFFIXES:
        if basename.endswith(suffix):
            return True

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

_CPP_LANG: Any = None


def _get_cpp_language() -> Any:
    """Return the tree-sitter Language for C++ (lazy singleton per process)."""
    global _CPP_LANG
    if _CPP_LANG is None:
        if not _TREE_SITTER_CPP_AVAILABLE:
            raise ImportError(
                "tree-sitter-cpp is not installed. "
                "Install with: pip install graphlint[cpp]"
            )
        import tree_sitter
        import tree_sitter_cpp

        _CPP_LANG = tree_sitter.Language(tree_sitter_cpp.language())
    return _CPP_LANG
