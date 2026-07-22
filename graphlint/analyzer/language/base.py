# -*- coding: utf-8 -*-
"""LanguageAdapter abstract base class — defines the contract for language backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable

from graphlint.analyzer._types import NodeInfo, ParseResult


class LanguageAdapter(ABC):
    """Abstract base class for language-specific analysis backends.

    Each target language (Python, Rust, etc.) implements one subclass.
    The framework interacts with all languages through this interface.
    """

    # ------------------------------------------------------------------
    # Identification
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def language_name(self) -> str:
        """Short identifier for the language (e.g. ``"python"``, ``"rust"``)."""

    @property
    @abstractmethod
    def file_extensions(self) -> frozenset[str]:
        """File extensions handled by this adapter (e.g. ``{".py"}``, ``{".rs"}``)."""

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def worker_function(self) -> Callable[..., "ParseResult"]:
        """Module-level function suitable for :class:`ProcessPoolExecutor`.

        Must be defined at module scope so it can be pickled.
        Signature: ``(file_path: str, root_dir: str, config: dict) -> ParseResult``
        """

    @abstractmethod
    def parse_file(
        self, full_path: str, root_dir: str, config: dict[str, Any]
    ) -> ParseResult:
        """Parse a single source file into structured nodes, imports and references.

        Args:
            full_path: Absolute path to the source file.
            root_dir: Project root directory for relative path computation.
            config: Language-specific configuration dictionary.

        Returns:
            A :class:`ParseResult` with nodes, imports, references and warnings.
        """

    # ------------------------------------------------------------------
    # Entry-point detection
    # ------------------------------------------------------------------

    @abstractmethod
    def detect_entries(
        self,
        parse_results: dict[str, ParseResult],
        nodes: list[NodeInfo],
        node_id_map: dict[int, NodeInfo],
        config: dict[str, Any],
    ) -> list[Any]:
        """Detect entry points in this language's parsed files.

        Returns:
            List of :class:`EntryInfo` objects identifying entry-point nodes.
        """

    # ------------------------------------------------------------------
    # Path / naming utilities
    # ------------------------------------------------------------------

    @abstractmethod
    def file_to_module(self, path: str) -> str:
        """Convert a file path to a fully-qualified module name.

        Example (Python): ``"pkg/sub/module.py"`` → ``"pkg.sub.module"``
        Example (Rust):   ``"src/lib.rs"`` → ``"crate"``
        """

    @abstractmethod
    def is_test_file(self, file_path: str, config: dict[str, Any]) -> bool:
        """Return ``True`` when *file_path* is a test file for this language."""

    # ------------------------------------------------------------------
    # Special names (implicitly-invoked symbols)
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def public_api_names(self) -> frozenset[str]:
        """Names with well-defined language-level semantics.

        These are exempt from "unused" / "write-only" warnings because
        the language runtime may access them implicitly.
        (Python: ``__all__``, ``__version__``, etc.)
        """

    @property
    @abstractmethod
    def special_names(self) -> frozenset[str]:
        """Method / function names invoked implicitly by the language runtime.

        These are exempt from dead-code detection because the runtime
        may call them without an explicit call site.
        (Python: ``__init__``, ``__str__``, ``__call__``, etc.)
        """

    # ------------------------------------------------------------------
    # File-system defaults
    # ------------------------------------------------------------------

    @property
    @abstractmethod
    def default_excludes(self) -> frozenset[str]:
        """Default directory / file patterns to exclude from scanning.

        (Python: ``__pycache__``, ``*.pyc``, ``.venv``, etc.)
        (Rust:   ``target``, ``.cargo``, etc.)
        """
        ...
