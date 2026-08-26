# -*- coding: utf-8 -*-
"""Unified C/C++ family adapter.

One adapter owns *every* C-family extension (``.c``, ``.h``, ``.cpp``, ``.cc``,
``.cxx``, ``.hpp``, ``.hh``, ``.hxx``) so graphlint treats a mixed C/C++
project as a single graph with one routing, one module-naming, one entry
surface and one shared type/method table.

Inside, each file is analysed with the grammar its *translation unit*'s
language dictates — exactly as a C/C++ compiler behaves, and never by content
sniffing a header:

- ``.c``              -> C grammar (tree-sitter-c)
- ``.cpp/.cc/.cxx/.hpp/.hh/.hxx`` -> C++ grammar (tree-sitter-cpp)
- ``.h``              -> the language of the TU(s) that include it:
                        ``cpp`` if only a C++ TU includes it, ``c`` if only C
                        TUs, and ``c`` (the shared subset) when both C and C++
                        TUs include it — a compiler only accepts a genuinely
                        shared header if it is valid as C.
"""

from __future__ import annotations

import os
import re
from typing import Any, Callable

from graphlint.analyzer._types import NodeInfo, ParseResult
from graphlint.analyzer.language.base import LanguageAdapter
from graphlint.analyzer.language.c import _C_ENTRY_FUNCTION_NAMES
from graphlint.analyzer.language.c.constants import (
    _C_DEFAULT_EXCLUDES,
    _C_PUBLIC_API_NAMES,
    _C_SPECIAL_NAMES,
    _is_test_file as _c_is_test_file,
)
from graphlint.analyzer.language.c.entry import CEntryPointDetector
from graphlint.analyzer.language.c.parser import _parse_file_worker as _c_parse_worker
from graphlint.analyzer.language.cpp.entry import CppEntryPointDetector
from graphlint.analyzer.language.cpp.constants import (
    _CPP_DEFAULT_EXCLUDES,
    _CPP_OPERATOR_NAMES,
    _CPP_PUBLIC_API_NAMES,
    _CPP_SPECIAL_NAMES,
    _is_test_file as _cpp_is_test_file,
)
from graphlint.analyzer.language.cpp.parser import _parse_file_worker as _cpp_parse_worker

_CPP_EXTS: frozenset[str] = frozenset({".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx"})
_C_EXTS: frozenset[str] = frozenset({".c", ".h"})
_ALL_C_FAMILY_EXTS: frozenset[str] = _CPP_EXTS | _C_EXTS

_INCLUDE_RE = re.compile(r'#\s*include\s*[<"]([^>"]+)[">]')


def _cfamily_file_to_module(path: str) -> str:
    """Convert a C/C++ source path to its module name (unified for the family).

    ``.c``/``.h`` and the C++ suffixes are all handled the same way, so a
    header ``engine/Service.h`` yields ``engine.Service`` regardless of the
    grammar it is parsed with.
    """
    lower = path.lower()
    for ext in sorted(_ALL_C_FAMILY_EXTS, key=len, reverse=True):
        if lower.endswith(ext):
            path_no_ext = path[: -len(ext)]
            break
    else:
        return ""
    normalized = path_no_ext.replace("\\", "/")
    parts = [p for p in normalized.split("/") if p]
    return ".".join(parts)


def _is_cpp_extension(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in _CPP_EXTS


# ---------------------------------------------------------------------------
# Compiler-faithful ``.h`` routing
# ---------------------------------------------------------------------------
#
# A header's language is the language of the TU(s) that include it.  We
# resolve that from the include graph (``#include`` is lexically identical in
# C/C++), not from the header's content.


def _resolve_include(inc_name: str, from_file: str, path_set: set[str],
                     base_index: dict[str, list[str]]) -> str | None:
    """Resolve an ``#include`` to an absolute C-family path, or ``None``."""
    cand = os.path.normpath(os.path.join(os.path.dirname(from_file), inc_name))
    abs_cand = os.path.abspath(cand)
    if abs_cand in path_set:
        return abs_cand
    matches = base_index.get(os.path.basename(inc_name), ())
    if len(matches) == 1:
        return matches[0]
    return None


def resolve_header_flavors(all_paths: list[str]) -> dict[str, str]:
    """Return ``{abs .h path: "c"|"cpp"}`` for header files.

    A header is ``cpp`` when only C++ TUs include it, ``c`` when any C TU
    includes it (or when it is only included by C TUs), and defaults to ``c``
    when nothing includes it.  Non-header paths are ignored (they are routed
    by extension).
    """
    all_paths = [os.path.abspath(p) for p in all_paths]
    path_set = set(all_paths)

    base_index: dict[str, list[str]] = {}
    for p in all_paths:
        base_index.setdefault(os.path.basename(p), []).append(p)

    # ``_cfamily_includes[abs_src] = [abs_included_header, ...]``
    includes: dict[str, list[str]] = {}
    for p in all_paths:
        ext = os.path.splitext(p)[1].lower()
        if ext not in _ALL_C_FAMILY_EXTS:
            continue
        try:
            with open(p, "r", encoding="utf-8", errors="replace") as fh:
                src = fh.read()
        except OSError:
            continue
        for inc_name in _INCLUDE_RE.findall(src):
            inc_path = _resolve_include(inc_name, p, path_set, base_index)
            if inc_path is not None:
                includes.setdefault(p, []).append(inc_path)

    # Reverse adjacency: included header -> [includer,...]
    rev: dict[str, list[str]] = {}
    for src, targets in includes.items():
        for t in targets:
            rev.setdefault(t, []).append(src)

    def ext_flavor(path: str) -> str:
        return "cpp" if _is_cpp_extension(path) else "c"

    # Fixpoint: headers resolve once their includers are known.
    flavor: dict[str, str | None] = {}
    for p in all_paths:
        if p.endswith(".h"):
            flavor[p] = None
        elif os.path.splitext(p)[1].lower() in _ALL_C_FAMILY_EXTS:
            flavor[p] = ext_flavor(p)

    changed = True
    while changed:
        changed = False
        for hdr, incs in rev.items():
            if hdr not in flavor or flavor[hdr] is not None:
                continue
            contribs: set[str] = set()
            for inc in incs:
                f = flavor.get(inc)
                if f is not None:
                    contribs.add(f)
            if not contribs:
                continue
            # Any C includer => shared/`c` (a compiler requires a truly shared
            # header to be C-valid).  Otherwise `cpp` when any C++ TU needs it.
            newf = "c" if "c" in contribs else "cpp"
            if newf != flavor[hdr]:
                flavor[hdr] = newf
                changed = True

    return {hdr: f if f is not None else "c" for hdr, f in flavor.items()}


def _header_flavor(path: str, config: dict[str, Any]) -> str:
    """Flavor for a ``.h`` given the project-wide resolver result."""
    flavors = config.get("_cfamily_header_flavors")
    if isinstance(flavors, dict):
        got = flavors.get(os.path.abspath(path))
        if got in ("c", "cpp"):
            return got
    return "c"


def _flavor_for_path(path: str, config: dict[str, Any]) -> str:
    """Deterministic file->flavour decision for a C-family path."""
    if path.lower().endswith(".h"):
        return _header_flavor(path, config)
    return "cpp" if _is_cpp_extension(path) else "c"


# ---------------------------------------------------------------------------
# Process-pool worker — picks the grammar from the file's flavour
# ---------------------------------------------------------------------------

_worker_cache: dict[str, Callable[..., ParseResult]] = {}


def _cfamily_parse_worker(
    full_path: str, root_dir: str, config: dict[str, Any],
) -> ParseResult:
    """Module-level worker: dispatch to the C or C++ parser by flavour."""
    flavor = _flavor_for_path(full_path, config)
    worker = _cpp_parse_worker if flavor == "cpp" else _c_parse_worker
    return worker(full_path, root_dir, config)


class CFamilyAdapter(LanguageAdapter):
    """Unified C/C++ analyzer owning every C-family extension.

    Requires ``tree-sitter-cpp`` for C++ files and ``tree-sitter-c`` for C
    files.  A missing grammar yields a per-file ``missing_dependency`` warning
    (graceful degradation), matching the previous per-language behaviour.
    """

    language_name = "c/cpp"
    file_extensions = _ALL_C_FAMILY_EXTS

    @property
    def worker_function(self) -> Callable[..., ParseResult]:
        return _cfamily_parse_worker

    def parse_file(
        self, full_path: str, root_dir: str, config: dict[str, Any]
    ) -> ParseResult:
        return _cfamily_parse_worker(full_path, root_dir, config)

    # ------------------------------------------------------------------
    # Entry detection — run each flavour through its own detector
    # ------------------------------------------------------------------

    def detect_entries(
        self,
        parse_results: dict[str, ParseResult],
        nodes: list[NodeInfo],
        node_id_map: dict[int, NodeInfo],
        config: dict[str, Any],
    ) -> list[Any]:
        c_prs: dict[str, ParseResult] = {}
        cpp_prs: dict[str, ParseResult] = {}
        for fp, pr in parse_results.items():
            if _flavor_for_path(fp, config) == "cpp":
                cpp_prs[fp] = pr
            else:
                c_prs[fp] = pr

        entries: list[Any] = []
        if c_prs:
            entries.extend(
                CEntryPointDetector(config).detect(c_prs, nodes, node_id_map)
            )
        if cpp_prs:
            entries.extend(
                CppEntryPointDetector(config).detect(cpp_prs, nodes, node_id_map)
            )
        return entries

    # ------------------------------------------------------------------
    # Path / naming utilities
    # ------------------------------------------------------------------

    def file_to_module(self, path: str) -> str:
        return _cfamily_file_to_module(path)

    def is_test_file(self, file_path: str, config: dict[str, Any]) -> bool:
        # A C++ test convention is more specific; delegate by flavour.
        return _cpp_is_test_file(file_path, config) or _c_is_test_file(file_path, config)

    # ------------------------------------------------------------------
    # Special / public names, excludes (union of C and C++)
    # ------------------------------------------------------------------

    @property
    def public_api_names(self) -> frozenset[str]:
        return _C_PUBLIC_API_NAMES | _CPP_PUBLIC_API_NAMES

    @property
    def special_names(self) -> frozenset[str]:
        return _C_SPECIAL_NAMES | _CPP_SPECIAL_NAMES

    def is_special_name(self, name: str) -> bool:
        """Implicitly-invoked names across the C/C++ family.

        C: the ``main`` family (``main``/``WinMain``/...).
        C++: the placeholder set plus destructors (``~Name``) and operator
        overloads anchored to the finite overloadable set, so a plain free
        function like ``operatorfoo`` is not treated as special.
        """
        if name in _C_SPECIAL_NAMES or name in _C_ENTRY_FUNCTION_NAMES:
            return True
        if name in _CPP_SPECIAL_NAMES:
            return True
        if name.startswith("~"):
            return True
        return name in _CPP_OPERATOR_NAMES

    @property
    def default_excludes(self) -> frozenset[str]:
        return _C_DEFAULT_EXCLUDES | _CPP_DEFAULT_EXCLUDES
