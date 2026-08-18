# -*- coding: utf-8 -*-
"""C-specific constants: file utilities, test detection, tree-sitter loader."""

from __future__ import annotations

import fnmatch
import os
import re
from functools import lru_cache
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


@lru_cache(maxsize=256)
def _compile_globs(pattern: str) -> tuple[re.Pattern, ...]:
    """Compile an fnmatch-style pattern (plus its ``**/``-stripped variant)."""
    variants = [pattern]
    if pattern.startswith("**/"):
        variants.append(pattern[3:])
    return tuple(
        re.compile(fnmatch.translate(os.path.normcase(v))) for v in variants
    )


@lru_cache(maxsize=65536)
def _glob_match(path: str, pattern: str) -> bool:
    """Match *path* against an fnmatch-style *pattern*.

    Semantics mirror ``fnmatch.fnmatch`` (case-insensitive via normcase on
    Windows), including the ``**/`` prefix fallback used by entry rules.
    Patterns are compiled once and results are memoized — ``fnmatch``
    re-translates and normcases both arguments on every call, which is
    expensive on Windows (normcase is an LCMapStringEx syscall per call).
    """
    if os.name == "nt" and path.isascii():
        # normcase semantics for ASCII input on Windows.
        norm = path.replace("/", "\\").lower()
    else:
        norm = os.path.normcase(path)
    return any(p.match(norm) for p in _compile_globs(pattern))


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

_C_TEST_FILE_SUFFIXES: tuple[str, ...] = ("_test.c", "_test.h")
_C_TEST_FILE_EXACT_NAMES: frozenset[str] = frozenset({"test.c", "test.h"})
_C_TEST_FILE_PREFIXES: tuple[str, ...] = ("test_",)


def _is_test_file(file_path: str, config: dict[str, Any]) -> bool:
    """Check whether *file_path* is a C test file."""
    basename = os.path.basename(file_path)

    for prefix in _C_TEST_FILE_PREFIXES:
        if basename.startswith(prefix):
            return True

    if basename in _C_TEST_FILE_EXACT_NAMES:
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
        _glob_match(dir_with_slash, d) or dir_with_slash.startswith(d)
        for d in dir_patterns
    ):
        return True

    if any(_glob_match(basename, p) for p in file_patterns):
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
