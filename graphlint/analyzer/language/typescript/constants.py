# -*- coding: utf-8 -*-
"""TypeScript/JavaScript-specific constants: availability flags, node-type
mappings, special names, excludes, utilities."""

from __future__ import annotations

import fnmatch
import os
from typing import Any

# ---------------------------------------------------------------------------
# Tree-sitter availability
# ---------------------------------------------------------------------------

_TREE_SITTER_TYPESCRIPT_AVAILABLE: bool = False
_TREE_SITTER_JAVASCRIPT_AVAILABLE: bool = False
try:
    import tree_sitter  # noqa: F401
    import tree_sitter_typescript  # noqa: F401

    _TREE_SITTER_TYPESCRIPT_AVAILABLE = True
except ImportError:
    pass

try:
    import tree_sitter  # noqa: F401
    import tree_sitter_javascript  # noqa: F401

    _TREE_SITTER_JAVASCRIPT_AVAILABLE = True
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Public API names (language-level semantics — exempt from unused warnings)
# ---------------------------------------------------------------------------

_TYPESCRIPT_PUBLIC_API_NAMES: frozenset[str] = frozenset(
    {
        "main",  # Common JS entry convention
    }
)

# ---------------------------------------------------------------------------
# Special names — methods invoked implicitly by the JS/TS runtime or compiler
# ---------------------------------------------------------------------------

# React lifecycle methods — invoked implicitly by the React runtime, so they
# must never be treated as dead code even when not referenced elsewhere.
_REACT_LIFECYCLE_NAMES: frozenset[str] = frozenset(
    {
        "render",
        "componentDidMount",
        "componentWillUnmount",
        "componentDidUpdate",
        "shouldComponentUpdate",
        "getDerivedStateFromProps",
        "getSnapshotBeforeUpdate",
        "componentDidCatch",
        "getDerivedStateFromError",
    }
)

# Genuine language/runtime-special names only. Deliberately narrow: names like
# ``get``/``set``/``apply``/``call``/``bind``/``then``/``catch``/``finally``/
# ``next``/``return``/``throw`` are ordinary JS identifiers that would
# over-suppress dead-code warnings for regular methods, so they are excluded.
_TYPESCRIPT_SPECIAL_NAMES: frozenset[str] = frozenset(
    {
        "constructor",
        "toString",
        "valueOf",
        "toJSON",
        "Symbol.iterator",
        "Symbol.asyncIterator",
        "Symbol.toPrimitive",
        "Symbol.toStringTag",
    }
) | _REACT_LIFECYCLE_NAMES

# ---------------------------------------------------------------------------
# Default exclude patterns
# ---------------------------------------------------------------------------

_TYPESCRIPT_DEFAULT_EXCLUDES: frozenset[str] = frozenset(
    {
        "node_modules",
        "dist",
        "build",
        ".next",
        ".nuxt",
        "coverage",
        ".git",
        ".svn",
        ".hg",
        ".idea",
        ".vscode",
        ".vs",
        ".graphlint",
        "__pycache__",
    }
)

# ---------------------------------------------------------------------------
# Tree-sitter CST → graphlint NodeInfo.node_type mapping
# ---------------------------------------------------------------------------

_CST_TYPE_TO_NODE_TYPE: dict[str, str] = {
    "class_declaration": "class",
    "abstract_class_declaration": "class",
    "interface_declaration": "interface",
    "enum_declaration": "enum",
    "type_alias_declaration": "type_alias",
    "function_declaration": "function",
    "generator_function_declaration": "function",
    "namespace_declaration": "namespace",
    "module": "module",
    "internal_module": "namespace",
}

_TYPE_MEMBER_NODE_TYPES: dict[str, str] = {
    "method_definition": "method",
    "public_field_definition": "property",
    "property_signature": "property",
    "call_signature": "method",
    "construct_signature": "constructor",
    "index_signature": "property",
    "get_accessor": "property",
    "set_accessor": "property",
}

# ---------------------------------------------------------------------------
# Path / naming utilities
# ---------------------------------------------------------------------------

_TS_FILE_EXTENSIONS: frozenset[str] = frozenset(
    {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts"}
)


def _is_tsx_file(path: str) -> bool:
    """Return True when *path* is a TSX file."""
    return any(path.endswith(ext) for ext in (".tsx", ".jsx"))


def _is_ts_file(path: str) -> bool:
    """Return True when *path* is a TypeScript file (includes .tsx)."""
    return any(path.endswith(ext) for ext in (".ts", ".tsx", ".mts", ".cts"))


def _is_js_file(path: str) -> bool:
    """Return True when *path* is a JavaScript file."""
    return any(path.endswith(ext) for ext in (".js", ".jsx", ".mjs", ".cjs"))


def _file_to_module(path: str) -> str:
    """Convert a TS/JS source path to its module name.

    >>> _file_to_module("services/AuthService.ts")
    'services.AuthService'
    >>> _file_to_module("src/components/Button.tsx")
    'src.components.Button'
    """
    ts_exts = (".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs")
    for ext in ts_exts:
        if path.endswith(ext):
            path_no_ext = path[: -len(ext)]
            break
    else:
        return ""

    normalized = path_no_ext.replace("\\", "/")
    parts = [p for p in normalized.split("/") if p]
    return ".".join(parts)


# ---------------------------------------------------------------------------
# Test file detection
# ---------------------------------------------------------------------------

_TS_TEST_FILE_SUFFIXES: tuple[str, ...] = (
    ".test.ts", ".spec.ts",
    ".test.tsx", ".spec.tsx",
    ".test.js", ".spec.js",
    ".test.jsx", ".spec.jsx",
    ".test.mjs", ".spec.mjs",
    ".test.cjs", ".spec.cjs",
    ".test.mts", ".spec.mts",
    ".test.cts", ".spec.cts",
)

_TS_DEFAULT_FILE_PATTERNS: tuple[str, ...] = (
    "*.test.ts", "*.spec.ts", "*.test.tsx", "*.spec.tsx",
    "*.test.js", "*.spec.js", "*.test.jsx", "*.spec.jsx",
    "*.test.mjs", "*.spec.mjs", "*.test.cjs", "*.spec.cjs",
    "*.test.mts", "*.spec.mts", "*.test.cts", "*.spec.cts",
)

_TS_DEFAULT_DIR_PATTERNS: tuple[str, ...] = (
    "__tests__/", "__test__/", "tests/", "test/", "spec/",
    "e2e/", "__mocks__/",
)


def _is_test_file(file_path: str, config: dict[str, Any]) -> bool:
    """Check whether *file_path* is a TS/JS test file.

    Test conventions match at ANY depth: ``src/__tests__/foo.ts`` and
    ``components/Button.test.tsx`` are both test files, not just root-level
    ``__tests__/`` or ``*.test.ts``.
    """
    test_patterns = config.get("test_patterns", {})
    file_patterns = test_patterns.get("file_patterns", list(_TS_DEFAULT_FILE_PATTERNS))
    dir_patterns = test_patterns.get("dir_patterns", list(_TS_DEFAULT_DIR_PATTERNS))

    normalized = file_path.replace("\\", "/")
    basename = os.path.basename(file_path)

    for suffix in _TS_TEST_FILE_SUFFIXES:
        if basename.endswith(suffix):
            return True

    # Directory-based detection at any depth: split the path into segments and
    # match any segment against the test directory conventions.
    segments = [s for s in normalized.split("/") if s]
    for d in _TS_DEFAULT_DIR_PATTERNS:
        d_clean = d.rstrip("/")
        if d_clean and d_clean in segments:
            return True

    # Config-provided dir patterns (also matched at any depth).
    for d in dir_patterns:
        d_clean = d.rstrip("/")
        if d_clean and d_clean in segments:
            return True

    if any(fnmatch.fnmatch(basename, p) for p in file_patterns):
        return True

    return False


# ---------------------------------------------------------------------------
# Tree-sitter Language singletons (lazy, per-process)
# ---------------------------------------------------------------------------

_TS_LANG: Any = None
_TSX_LANG: Any = None
_JS_LANG: Any = None


def _get_typescript_language() -> Any:
    """Return the tree-sitter Language for TypeScript."""
    global _TS_LANG
    if _TS_LANG is None:
        if not _TREE_SITTER_TYPESCRIPT_AVAILABLE:
            raise ImportError(
                "tree-sitter-typescript is not installed. "
                "Install with: pip install graphlint[typescript]"
            )
        import tree_sitter
        import tree_sitter_typescript

        _TS_LANG = tree_sitter.Language(tree_sitter_typescript.language_typescript())
    return _TS_LANG


def _get_tsx_language() -> Any:
    """Return the tree-sitter Language for TSX."""
    global _TSX_LANG
    if _TSX_LANG is None:
        if not _TREE_SITTER_TYPESCRIPT_AVAILABLE:
            raise ImportError(
                "tree-sitter-typescript is not installed. "
                "Install with: pip install graphlint[typescript]"
            )
        import tree_sitter
        import tree_sitter_typescript

        _TSX_LANG = tree_sitter.Language(tree_sitter_typescript.language_tsx())
    return _TSX_LANG


def _get_javascript_language() -> Any:
    """Return the tree-sitter Language for JavaScript."""
    global _JS_LANG
    if _JS_LANG is None:
        if not _TREE_SITTER_JAVASCRIPT_AVAILABLE:
            raise ImportError(
                "tree-sitter-javascript is not installed. "
                "Install with: pip install graphlint[typescript]"
            )
        import tree_sitter
        import tree_sitter_javascript

        _JS_LANG = tree_sitter.Language(tree_sitter_javascript.language())
    return _JS_LANG


def _get_parser_language_for_file(file_path: str) -> Any:
    """Return the appropriate tree-sitter Language for a file path."""
    if _is_tsx_file(file_path):
        return _get_tsx_language()
    if _is_ts_file(file_path):
        return _get_typescript_language()
    return _get_javascript_language()
