# -*- coding: utf-8 -*-
"""LanguageRegistry — discovers and caches language adapters by file extension."""

from __future__ import annotations

import os
from typing import Optional

from graphlint.analyzer.language.base import LanguageAdapter

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
    """Central registry that maps file extensions to language adapters."""

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
        """Return the adapter that handles *path*, or ``None``."""
        _, ext = os.path.splitext(path)
        if ext and ext.startswith("."):
            key = ext.lower()
            return self._by_extension.get(key)
        return None

    def adapter_for_language(self, name: str) -> Optional[LanguageAdapter]:
        """Return the adapter whose :attr:`language_name` matches *name*."""
        for adapter in self._adapters:
            if adapter.language_name == name:
                return adapter
        return None

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

    # ------------------------------------------------------------------
    # Bulk queries
    # ------------------------------------------------------------------

    def all_extensions(self) -> frozenset[str]:
        """Union of all file extensions across every registered adapter."""
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
