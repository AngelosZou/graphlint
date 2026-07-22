# -*- coding: utf-8 -*-
"""Python-specific constants: entry rules, dunder names, excludes, utilities."""

from __future__ import annotations

import fnmatch
import os
from typing import Any

# ---------------------------------------------------------------------------
# Public API dunder names (language-level semantics)
# ---------------------------------------------------------------------------

_PYTHON_PUBLIC_API_DUNDERS: frozenset[str] = frozenset(
    {
        "__all__",
        "__version__",
        "__author__",
        "__copyright__",
        "__license__",
        "__credits__",
    }
)

# ---------------------------------------------------------------------------
# Special method names (Python data model — invoked implicitly)
# ---------------------------------------------------------------------------

_PYTHON_SPECIAL_METHOD_DUNDERS: frozenset[str] = frozenset(
    {
        # Object lifecycle
        "__new__",
        "__init__",
        "__del__",
        # String representation
        "__repr__",
        "__str__",
        "__format__",
        "__bytes__",
        # Container methods
        "__len__",
        "__getitem__",
        "__setitem__",
        "__delitem__",
        "__contains__",
        "__iter__",
        "__next__",
        "__reversed__",
        # Callable
        "__call__",
        # Context manager
        "__enter__",
        "__exit__",
        "__aenter__",
        "__aexit__",
        # Attribute access
        "__getattr__",
        "__setattr__",
        "__delattr__",
        "__getattribute__",
        # Descriptor
        "__get__",
        "__set__",
        "__delete__",
        "__set_name__",
        # Numeric operators
        "__add__",
        "__sub__",
        "__mul__",
        "__matmul__",
        "__truediv__",
        "__floordiv__",
        "__mod__",
        "__divmod__",
        "__pow__",
        "__lshift__",
        "__rshift__",
        "__and__",
        "__xor__",
        "__or__",
        # Reflected numeric
        "__radd__",
        "__rsub__",
        "__rmul__",
        "__rmatmul__",
        "__rtruediv__",
        "__rfloordiv__",
        "__rmod__",
        "__rdivmod__",
        "__rpow__",
        "__rlshift__",
        "__rrshift__",
        "__rand__",
        "__rxor__",
        "__ror__",
        # In-place operators
        "__iadd__",
        "__isub__",
        "__imul__",
        "__imatmul__",
        "__itruediv__",
        "__ifloordiv__",
        "__imod__",
        "__ipow__",
        "__ilshift__",
        "__irshift__",
        "__iand__",
        "__ixor__",
        "__ior__",
        # Unary operators
        "__neg__",
        "__pos__",
        "__abs__",
        "__invert__",
        # Type conversion
        "__int__",
        "__float__",
        "__complex__",
        "__bool__",
        "__index__",
        # Comparison
        "__lt__",
        "__le__",
        "__eq__",
        "__ne__",
        "__gt__",
        "__ge__",
        "__hash__",
        # Async
        "__await__",
        "__aiter__",
        "__anext__",
        # Class protocols
        "__init_subclass__",
        "__class_getitem__",
        # Pickle / copy
        "__reduce__",
        "__reduce_ex__",
        "__getnewargs__",
        "__getstate__",
        "__setstate__",
        "__copy__",
        "__deepcopy__",
    }
)

# ---------------------------------------------------------------------------
# Default exclude patterns
# ---------------------------------------------------------------------------

_PYTHON_DEFAULT_EXCLUDES: frozenset[str] = frozenset(
    {
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".tox",
        ".venv",
        "venv",
        "env",
        "virtualenv",
        ".env",
        ".egg-info/",
        "*.pyc",
        "*.pyo",
    }
)

# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _file_to_module(path: str) -> str:
    """Convert a Python file path to dotted module name."""
    if path.endswith(".py"):
        path = path[:-3]
    return path.replace("/", ".").replace("\\", ".")


def _is_test_file(file_path: str, config: dict[str, Any]) -> bool:
    """Check whether *file_path* is a Python test file."""
    test_patterns = config.get("test_patterns", {})
    file_patterns = test_patterns.get("file_patterns", ["test_*.py", "*_test.py"])
    dir_patterns = test_patterns.get("dir_patterns", ["tests/", "test/", "__tests__/"])
    config_files = test_patterns.get("config_files", ["conftest.py"])

    basename = os.path.basename(file_path)
    dirname = os.path.dirname(file_path).replace(os.sep, "/")

    if any(fnmatch.fnmatch(basename, p) for p in file_patterns):
        return True
    if any(fnmatch.fnmatch(basename, c) for c in config_files):
        return True
    if any(
        fnmatch.fnmatch(dirname + "/", d) or (dirname + "/").startswith(d)
        for d in dir_patterns
    ):
        return True

    return False
