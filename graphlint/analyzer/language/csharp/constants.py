# -*- coding: utf-8 -*-
"""C#-specific constants: special names, excludes, node-type mappings,
utilities."""

from __future__ import annotations

import fnmatch
import os
import re
from typing import Any

# ---------------------------------------------------------------------------
# Tree-sitter availability
# ---------------------------------------------------------------------------

_TREE_SITTER_CSHARP_AVAILABLE: bool = False
try:
    import tree_sitter  # noqa: F401
    import tree_sitter_c_sharp  # noqa: F401

    _TREE_SITTER_CSHARP_AVAILABLE = True
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Public API names (language-level semantics — exempt from unused warnings)
# ---------------------------------------------------------------------------

_CSHARP_PUBLIC_API_NAMES: frozenset[str] = frozenset(
    {
        "Main",  # Program entry point — called by the OS runtime
    }
)

# ---------------------------------------------------------------------------
# Special names — methods invoked implicitly by the C# runtime or compiler
# ---------------------------------------------------------------------------

_CSHARP_SPECIAL_NAMES: frozenset[str] = frozenset(
    {
        # Constructors (called by ``new`` operator)
        ".ctor",
        ".cctor",
        # Destructor / finalizer (called by GC)
        "Finalize",
        # Object virtuals (called by runtime/GC/framework)
        "ToString",
        "Equals",
        "GetHashCode",
        "MemberwiseClone",
        "GetType",
        # IDisposable pattern (called by ``using`` / ``await using``)
        "Dispose",
        "DisposeAsync",
        # IEnumerable / foreach pattern (called by compiler)
        "GetEnumerator",
        "MoveNext",
        "Reset",
        # Await pattern (called by compiler)
        "GetAwaiter",
        "GetResult",
        "IsCompleted",
        "OnCompleted",
        "UnsafeOnCompleted",
        # Deconstruct (called by tuple deconstruction)
        "Deconstruct",
        # Collection initializer
        "Add",
        # Delegate invocation
        "Invoke",
        "BeginInvoke",
        "EndInvoke",
        # Operator overloads (called by compiler)
        "op_Addition",
        "op_Subtraction",
        "op_Multiply",
        "op_Division",
        "op_Modulus",
        "op_ExclusiveOr",
        "op_BitwiseAnd",
        "op_BitwiseOr",
        "op_LeftShift",
        "op_RightShift",
        "op_OnesComplement",
        "op_Equality",
        "op_Inequality",
        "op_LessThan",
        "op_GreaterThan",
        "op_LessThanOrEqual",
        "op_GreaterThanOrEqual",
        "op_Decrement",
        "op_Increment",
        "op_UnaryNegation",
        "op_UnaryPlus",
        "op_LogicalNot",
        "op_True",
        "op_False",
        "op_Implicit",
        "op_Explicit",
    }
)

# ---------------------------------------------------------------------------
# Property accessor prefixes — ``get_X`` / ``set_X`` are compiler-invoked;
# matched by suffix at special-name check time.
# ---------------------------------------------------------------------------

_PROPERTY_ACCESSOR_SPECIALS: frozenset[str] = frozenset({"get_", "set_", "init_"})


def _is_property_accessor(name: str) -> bool:
    """Return True when *name* is a compiler-generated property accessor."""
    for prefix in _PROPERTY_ACCESSOR_SPECIALS:
        if name.startswith(prefix) and len(name) > len(prefix):
            return True
    return False


# ---------------------------------------------------------------------------
# Default exclude patterns
# ---------------------------------------------------------------------------

_CSHARP_DEFAULT_EXCLUDES: frozenset[str] = frozenset(
    {
        "bin",
        "obj",
        ".vs",
        "packages",
        ".idea",
    }
)

# ---------------------------------------------------------------------------
# Tree-sitter CST → graphlint NodeInfo.node_type mapping
# ---------------------------------------------------------------------------

_CST_TYPE_TO_NODE_TYPE: dict[str, str] = {
    "class_declaration": "class",
    "struct_declaration": "struct",
    "interface_declaration": "interface",
    "enum_declaration": "enum",
    "delegate_declaration": "delegate",
    "record_declaration": "record",
}

# Node types for items that appear inside type declarations
_TYPE_MEMBER_NODE_TYPES: dict[str, str] = {
    "method_declaration": "method",
    "constructor_declaration": "constructor",
    "destructor_declaration": "destructor",
    "property_declaration": "property",
    "indexer_declaration": "indexer",
    "operator_declaration": "operator",
    "conversion_operator_declaration": "operator",
    "event_declaration": "event",
    "event_field_declaration": "event",
    "field_declaration": "field",
}

# ---------------------------------------------------------------------------
# .csproj parsing — discover project-level information
# ---------------------------------------------------------------------------


def _parse_csproj_info(root_dir: str) -> dict[str, Any]:
    """Parse .csproj files to discover assembly names and test project flags.

    Returns a dict keyed by relative .csproj path with per-project metadata.
    """
    projects: dict[str, Any] = {}
    for dp, dns, fns in os.walk(root_dir):
        dns[:] = [
            d for d in dns
            if not d.startswith(".")
            and d not in ("bin", "obj", "node_modules", "packages", ".git", ".vs", ".idea")
        ]
        for fn in fns:
            if not fn.endswith(".csproj"):
                continue
            fp = os.path.join(dp, fn)
            rel = os.path.relpath(fp, root_dir).replace(os.sep, "/")
            info = _parse_single_csproj(fp)
            if info:
                projects[rel] = info
    return projects


def _read_csproj(path: str) -> str | None:
    """Read a .csproj file, tolerating BOMs and UTF-16 encodings.

    Visual Studio writes .csproj files as UTF-16 LE with BOM in some
    configurations; a plain ``utf-8`` read raises ``UnicodeDecodeError``
    and the whole project's metadata silently disappears.  Mirrors
    :func:`graphlint.analyzer.language.csharp.parser._read_source` but
    adds UTF-16 support and guards against mis-decoding UTF-16 content
    without a BOM (which decodes as UTF-8 without raising).
    """
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError:
        return None
    for enc in ("utf-8-sig", "utf-16", "latin-1"):
        try:
            text = raw.decode(enc)
        except UnicodeDecodeError:
            continue
        if "\x00" in text:
            # UTF-8 read of UTF-16 content (no BOM) — NUL bytes interleave
            continue
        return text
    return None


def _parse_single_csproj(path: str) -> dict[str, Any] | None:
    """Extract basic metadata from a single .csproj file."""
    content = _read_csproj(path)
    if content is None:
        return None

    info: dict[str, Any] = {"is_test_project": False, "target_framework": "", "output_type": ""}

    # Check for test SDK references
    if re.search(r'Microsoft\.NET\.Test\.Sdk', content):
        info["is_test_project"] = True
    if re.search(
        r'xunit\.runner\.visualstudio|MSTest\.TestAdapter|NUnit3TestAdapter',
        content,
        re.IGNORECASE,
    ):
        info["is_test_project"] = True
    # Check for test project type GUID (value-aware, attribute-tolerant)
    m = re.search(
        r'<TestProjectType\b[^>]*>\s*([^<]+?)\s*</TestProjectType>',
        content,
        re.IGNORECASE,
    )
    if m and m.group(1).strip().lower() not in ("false", ""):
        info["is_test_project"] = True
    # Explicit <IsTestProject> value overrides inherited settings
    # (e.g. a Directory.Build.props defaulting to test).
    m = re.search(
        r'<IsTestProject\b[^>]*>\s*([^<]+?)\s*</IsTestProject>',
        content,
        re.IGNORECASE,
    )
    if m:
        if m.group(1).strip().lower() == "false":
            info["is_test_project"] = False
        elif m.group(1).strip().lower() == "true":
            info["is_test_project"] = True

    # Elements may carry attributes: <OutputType Condition="...">
    m = re.search(
        r'<OutputType\b[^>]*>\s*([^<]+?)\s*</OutputType>',
        content,
        re.IGNORECASE,
    )
    if m:
        info["output_type"] = m.group(1).strip()
    # SDK-style projects default to Library when OutputType is absent

    # Extract target framework
    m = re.search(
        r'<TargetFramework[s]?\b[^>]*>\s*([^<]+?)\s*</TargetFramework[s]?>',
        content,
        re.IGNORECASE,
    )
    if m:
        info["target_framework"] = m.group(1).strip()

    # Extract assembly name
    m = re.search(r'<AssemblyName\b[^>]*>\s*([^<]+?)\s*</AssemblyName>', content, re.IGNORECASE)
    if m:
        info["assembly_name"] = m.group(1).strip()

    # Extract root namespace
    m = re.search(r'<RootNamespace\b[^>]*>\s*([^<]+?)\s*</RootNamespace>', content, re.IGNORECASE)
    if m:
        info["root_namespace"] = m.group(1).strip()

    return info


# ---------------------------------------------------------------------------
# File → csproj mapping
# ---------------------------------------------------------------------------


def _ensure_csproj_cache(config: dict[str, Any]) -> dict[str, Any]:
    """Lazy-load csproj cache into *config* and return it.

    The cache maps csproj relative path → parsed project info dict.
    Also builds a ``_csproj_dir_map`` for fast file→project lookups.
    """
    if "_csproj_cache" not in config:
        root_dir = config.get("_root_dir", os.getcwd())
        cache = _parse_csproj_info(root_dir)
        config["_csproj_cache"] = cache
        # Build dir→csproj_rel_path index for O(1) file→project lookups
        dir_map: dict[str, str] = {}
        for csproj_rel in cache:
            csproj_dir = os.path.dirname(csproj_rel).replace("\\", "/")
            if not csproj_dir or csproj_dir == ".":
                csproj_dir = ""
            dir_map[csproj_dir] = csproj_rel
        config["_csproj_dir_map"] = dir_map
    return config["_csproj_cache"]


def _get_csproj_for_file(file_path: str, config: dict[str, Any]) -> dict[str, Any] | None:
    """Find the owning .csproj info for a .cs source file.

    Walks up from *file_path*'s directory to find the nearest .csproj.
    Returns ``None`` when no .csproj is found.
    """
    cache = config.get("_csproj_cache")
    dir_map = config.get("_csproj_dir_map", {})
    if not cache or not dir_map:
        return None

    file_dir = os.path.dirname(file_path).replace("\\", "/")
    while True:
        if file_dir in dir_map:
            return cache.get(dir_map[file_dir])
        if file_dir == "" or "/" not in file_dir:
            # Check root-level csproj (dir_map key "")
            if "" in dir_map:
                return cache.get(dir_map[""])
            break
        file_dir = file_dir.rsplit("/", 1)[0]
    return None


def _csproj_dir_for_file(file_path: str, config: dict[str, Any]) -> str:
    """Return the owning .csproj's directory (relative), or ``""``."""
    dir_map = config.get("_csproj_dir_map", {})
    if not dir_map:
        return ""
    file_dir = os.path.dirname(file_path).replace("\\", "/")
    while True:
        if file_dir in dir_map:
            return file_dir
        if file_dir == "" or "/" not in file_dir:
            return ""
        file_dir = file_dir.rsplit("/", 1)[0]
    return ""


def _module_qname_for_file(file_path: str, config: dict[str, Any]) -> str:
    """Compute a file's module qname, honouring csproj ``RootNamespace``.

    When the owning project declares a ``RootNamespace``, the module name is
    ``RootNamespace.<relative-path-from-project-dir>`` (e.g. a file at
    ``src/MyApp/Services/AuthService.cs`` with ``RootNamespace=MyApp`` becomes
    ``MyApp.Services.AuthService``).  Otherwise the plain path-derived name is
    used, and a missing csproj cache falls back to the plain name too.
    """
    _ensure_csproj_cache(config)
    info = _get_csproj_for_file(file_path, config)
    root_ns = (info or {}).get("root_namespace", "")
    if not root_ns:
        return _file_to_module(file_path)
    csproj_dir = _csproj_dir_for_file(file_path, config)
    rel = file_path
    if csproj_dir and rel.startswith(csproj_dir + "/"):
        rel = rel[len(csproj_dir) + 1:]
    return _file_to_module(root_ns + "/" + rel)


# ---------------------------------------------------------------------------
# Path / naming utilities
# ---------------------------------------------------------------------------


def _file_to_module(path: str) -> str:
    """Convert a C# source path to its namespace-qualified name.

    >>> _file_to_module("Services/AuthService.cs")
    'Services.AuthService'
    >>> _file_to_module("src/MyApp/Services/AuthService.cs")
    'src.MyApp.Services.AuthService'
    """
    if not path.endswith(".cs"):
        return ""

    path_no_ext = path[:-3]
    normalized = path_no_ext.replace("\\", "/")
    parts = [p for p in normalized.split("/") if p]
    return ".".join(parts)


# ---------------------------------------------------------------------------
# Test file detection
# ---------------------------------------------------------------------------

_CSHARP_TEST_FILE_SUFFIXES: tuple[str, ...] = ("Tests.cs", "Test.cs", ".Tests.cs")
_CSHARP_DEFAULT_FILE_PATTERNS: tuple[str, ...] = ("*Tests.cs", "*Test.cs", "*.Tests.cs")
_CSHARP_DEFAULT_DIR_PATTERNS: tuple[str, ...] = ("Tests/", "tests/", "Test/", "test/")


def _is_test_file(file_path: str, config: dict[str, Any]) -> bool:
    """Check whether *file_path* is a C# test file.

    Uses csproj data (``is_test_project``) as the primary signal when
    available — it is more authoritative than naming conventions.
    Falls back to filename and directory pattern matching.
    """
    csproj_info = _get_csproj_for_file(file_path, config)
    if csproj_info and csproj_info.get("is_test_project"):
        return True

    test_patterns = config.get("test_patterns", {})
    file_patterns = test_patterns.get("file_patterns", list(_CSHARP_DEFAULT_FILE_PATTERNS))
    dir_patterns = test_patterns.get("dir_patterns", list(_CSHARP_DEFAULT_DIR_PATTERNS))

    normalized = file_path.replace("\\", "/")
    basename = os.path.basename(file_path)
    dirname = os.path.dirname(file_path).replace(os.sep, "/")

    for d in _CSHARP_DEFAULT_DIR_PATTERNS:
        if normalized == d.rstrip("/") or normalized.startswith(d):
            return True

    for suffix in _CSHARP_TEST_FILE_SUFFIXES:
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

_CSHARP_LANG: Any = None


def _get_csharp_language() -> Any:
    """Return the tree-sitter Language for C# (lazy singleton per process)."""
    global _CSHARP_LANG
    if _CSHARP_LANG is None:
        if not _TREE_SITTER_CSHARP_AVAILABLE:
            raise ImportError(
                "tree-sitter-c-sharp is not installed. "
                "Install with: pip install graphlint[csharp]"
            )
        import tree_sitter
        import tree_sitter_c_sharp

        _CSHARP_LANG = tree_sitter.Language(tree_sitter_c_sharp.language())
    return _CSHARP_LANG
