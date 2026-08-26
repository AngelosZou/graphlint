# -*- coding: utf-8 -*-
"""Language registry — maps file extensions to language adapters."""

from __future__ import annotations

import os
import re
from typing import Optional

from graphlint.analyzer.language.base import LanguageAdapter

_HEADER_SNIFF_READ_BYTES: int = 64 * 1024

# Word-bounded, token-level C++ markers. ``\\b`` around a keyword or symbol
# keeps plain-C identifiers (e.g. a struct field named ``class_id``) from
# tripping the C++ route, and the bare keyword never fires inside a comment or
# string (those are stripped before matching). Plain-C constructs (``struct``,
# ``#include <stdio.h>``) produce no C++ signal and stay on the C route.
_HEADER_CPP_RE = re.compile(
    r"\bclass\s+[A-Za-z_]\w*"
    r"|\bnamespace\s+[A-Za-z_]"
    r"|\btemplate\s*<"
    r"|\bclass\s*[A-Za-z_]\w*\s*[:{]"
    r"|\boperator\s*(?:load|store)?\b"
    r"|\bstd::"
    r"|\bconstexpr\b"
    r"|\bnullptr\b"
    r"|\breinterpret_cast\b|\bconst_cast\b|\bstatic_cast\b|\bdynamic_cast\b"
    r"|\bexplicit\b|\bvirtual\b|\bfriend\b|\btypename\b|\bmutable\b|\bnoexcept\b"
    r"|\bpublic\s*:|\bprivate\s*:|\bprotected\s*:"
)

_HEADER_CPP_INCLUDE_RE = re.compile(
    r"#\s*include\s*[<\"][^>\"]*\.(?:hpp|hh|hxx|cc|cpp)[\">]"
    r"|#\s*include\s*<\s*"
    r"(?:"
    r"iostream|istream|ostream|streambuf|sstream|fstream"
    r"|algorithm|vector|string|array|map|set|unordered_map|iterator"
    r"|memory|utility|typeinfo|functional|numeric|cstdint|cstring"
    r"|thread|mutex|atomic|chrono|future|condition_variable"
    r"|optional|variant|any|tuple|list|deque|stack|queue|bitset"
    r")\s*>"
)

_HEADER_C_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_HEADER_LINE_COMMENT_RE = re.compile(r"//[^\n]*|#[^\n]*")


def _strip_header_comments(text: str) -> str:
    """Strip ``/*...*/``, ``//`` line, and C preprocessor ``#...`` comments so
    C++ markers inside comments or directives don't mis-route the header."""
    text = _HEADER_C_COMMENT_RE.sub(" ", text)
    return _HEADER_LINE_COMMENT_RE.sub(" ", text)


def _strip_header_comment_only(text: str) -> str:
    """Strip ``/*...*/`` and ``//`` line comments only, keeping preprocessor
    directives intact.  Used for the C++ ``#include`` signals, which are real
    directives and must survive comment removal while comment-embedded
    ``#include <...>`` lines are cleared."""
    text = _HEADER_C_COMMENT_RE.sub(" ", text)
    return re.sub(r"//[^\n]*", " ", text)


def sniff_header_language(path: str) -> str:
    """Route a ``.h`` header to a language by content.

    Reads the first :data:`_HEADER_SNIFF_READ_BYTES` bytes of *path*, strips
    comments/directives, and looks for a C++-only construct. Returns ``"cpp"``
    when a strong C++ marker is found, else ``"c"`` (backward compatible —
    headers with no signal stay C).

    Conservative by design: plain-C headers (``struct`` + ``#include <stdio.h>``)
    must never be mis-routed to the C++ adapter.
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            head = fh.read(_HEADER_SNIFF_READ_BYTES)
    except (OSError, UnicodeError):
        return "c"
    stripped = _strip_header_comments(head)
    if _HEADER_CPP_RE.search(stripped):
        return "cpp"
    # The C++ ``#include`` signals are directives, so they must be matched on
    # comment-*only*-stripped text (directives preserved): a real
    # ``#include <vector>`` counts, but one embedded in a ``//`` or ``/* */``
    # comment does not.
    if _HEADER_CPP_INCLUDE_RE.search(_strip_header_comment_only(head)):
        return "cpp"
    return "c"

_COMMON_EXCLUDE_DIRS: frozenset[str] = frozenset(
    {
        "node_modules",
        ".git",
        ".svn",
        ".hg",
        ".idea",
        ".vscode",
        ".vs",
        ".graphlint",
        "build",
        "dist",
    }
)


class LanguageRegistry:
    """Central registry mapping file extensions to adapters."""

    def __init__(self) -> None:
        self._by_extension: dict[str, LanguageAdapter] = {}
        self._adapters: list[LanguageAdapter] = []

    def register(self, adapter: LanguageAdapter) -> None:
        """Register a language adapter."""
        for ext in adapter.file_extensions:
            self._by_extension[ext] = adapter
        self._adapters.append(adapter)

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def adapter_for_file(self, path: str) -> Optional[LanguageAdapter]:
        """Return the adapter that handles *path*, or ``None``.

        Extension-based for all unambiguous suffixes (``.c`` → C,
        ``.cpp/.hpp/...`` → C++). An ambiguous ``.h`` is routed by content
        (see :func:`sniff_header_language`) so that a header sniffed as C++
        resolves to the C++ adapter in every graph stage — module naming,
        special-name / public-API checks, entry detection and adapter result
        filtering — not just at parse time.
        """
        _, ext = os.path.splitext(path)
        if ext and ext.startswith("."):
            key = ext.lower()
            if key == ".h":
                return self._adapter_for_header(path)
            return self._by_extension.get(key)
        return None

    def _adapter_for_header(self, path: str) -> Optional[LanguageAdapter]:
        """Sniff ``.h`` content and return the C-family adapter it belongs to."""
        language: str = sniff_header_language(path)
        for adapter in self._adapters:
            if adapter.language_name == language:
                return adapter
        return self._by_extension.get(".h")

    def adapter_for_parsing(self, path: str) -> Optional[LanguageAdapter]:
        """Pick the adapter used to *parse* *path*.

        Uses the same single decision path as :meth:`adapter_for_file`: an
        ambiguous ``.h`` is routed by content, non-ambiguous extensions
        purely by extension.
        """
        return self.adapter_for_file(path)

    # ------------------------------------------------------------------
    # File-system scanning
    # ------------------------------------------------------------------

    def scan_files(
        self, root_dir: str
    ) -> list[tuple[str, int]]:
        """Walk *root_dir* and return ``(rel_path, mtime_ns)`` for every
        source file matching a registered language extension.

        This is the single source of truth for file discovery — both the
        change-detection stamp and the indexer delegate here.
        """
        result: list[tuple[str, int]] = []
        lang_exts = self.all_extensions()
        exclude_dirs = _COMMON_EXCLUDE_DIRS | self.all_default_excludes()

        for dp, dns, fns in os.walk(root_dir, topdown=True, followlinks=False):
            dns[:] = [
                d
                for d in dns
                if d not in exclude_dirs
                and not d.endswith(".egg-info")
                and not d.startswith(".")
            ]
            for fn in fns:
                ext = os.path.splitext(fn)[1].lower()
                if ext not in lang_exts:
                    continue
                if fn.endswith((".pyc", ".pyo")):
                    continue
                if fn.startswith("."):
                    continue
                fp = os.path.join(dp, fn)
                rel = os.path.relpath(fp, root_dir).replace(os.sep, "/")
                try:
                    mtime = os.stat(fp).st_mtime_ns
                except OSError:
                    continue
                result.append((rel, mtime))
        return result

    def detect_unhandled(
        self, root_dir: str, known_exts: frozenset[str]
    ) -> dict[str, int]:
        """Count files of a known language with no registered adapter.

        ``known_exts`` are extensions this tool understands but that are
        not currently registered.  Uses the same exclusion rules as
        :meth:`scan_files`.  Returns ``{ext: count}`` for every
        known-but-unhandled extension actually found.
        """
        lang_exts = self.all_extensions()
        exclude_dirs = _COMMON_EXCLUDE_DIRS | self.all_default_excludes()
        missing: dict[str, int] = {}
        for dp, dns, fns in os.walk(root_dir, topdown=True, followlinks=False):
            dns[:] = [
                d
                for d in dns
                if d not in exclude_dirs
                and not d.endswith(".egg-info")
                and not d.startswith(".")
            ]
            for fn in fns:
                if fn.startswith("."):
                    continue
                ext = os.path.splitext(fn)[1].lower()
                if ext in known_exts and ext not in lang_exts:
                    missing[ext] = missing.get(ext, 0) + 1
        return missing

    # ------------------------------------------------------------------
    # Bulk queries
    # ------------------------------------------------------------------

    def all_extensions(self) -> frozenset[str]:
        """Union of file extensions across all registered adapters."""
        exts: set[str] = set()
        for adapter in self._adapters:
            exts.update(adapter.file_extensions)
        return frozenset(exts)

    def all_adapters(self) -> list[LanguageAdapter]:
        """Return every registered adapter (copy)."""
        return list(self._adapters)

    def all_default_excludes(self) -> frozenset[str]:
        """Union of default-exclude patterns across all adapters."""
        excludes: set[str] = set()
        for adapter in self._adapters:
            excludes.update(adapter.default_excludes)
        return frozenset(excludes)

    def public_api_names(self) -> frozenset[str]:
        """Union of :attr:`public_api_names` across all adapters."""
        names: set[str] = set()
        for adapter in self._adapters:
            names.update(adapter.public_api_names)
        return frozenset(names)

    def special_names(self) -> frozenset[str]:
        """Union of :attr:`special_names` across all adapters."""
        names: set[str] = set()
        for adapter in self._adapters:
            names.update(adapter.special_names)
        return frozenset(names)
