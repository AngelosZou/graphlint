# -*- coding: utf-8 -*-
"""graphlint — Code Dependency Graph Analyzer."""

from typing import Any

__version__ = "0.1.0"

__all__ = ["query", "build", "configure", "__version__"]


def __getattr__(name: str) -> Any:
    """Lazy import public API names."""
    if name == "query":
        from graphlint.api import query as _query

        return _query
    if name == "build":
        from graphlint.api import build as _build

        return _build
    if name == "configure":
        from graphlint.api import configure as _configure

        return _configure
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
