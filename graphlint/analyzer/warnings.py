# -*- coding: utf-8 -*-
"""Warning collector — collects, deduplicates, and summarizes warnings."""

from __future__ import annotations

import os

from dataclasses import dataclass
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WARN_TYPE_VALUES: frozenset[str] = frozenset(
    {
        "unused_import",
        "dynamic_import",
        "circular_ref",
        "syntax_error",
        "write_only",
        "deprecated_usage",
        "dead_code",
        "type_mismatch",
        "unresolved_ref",
        "unused_variable",
        "file_too_large",
    }
)

# Keep in sync with params.py
VALID_WARN_TYPES: frozenset[str] = WARN_TYPE_VALUES

# Module-level dunder names that are semantically meaningful Python conventions
# even when never explicitly read/written within the module's own code.
_PUBLIC_API_DUNDERS: frozenset[str] = frozenset(
    {
        "__all__",
        "__version__",
        "__author__",
        "__copyright__",
        "__license__",
        "__credits__",
    }
)

# Class special method names (Python data model / magic methods) whose
# overload should be treated as belonging to the parent class even when
# no explicit CALL path exists — they may be invoked implicitly by the
# interpreter via syntactic constructs (with, str(), len(), etc.).
_SPECIAL_METHOD_DUNDERS: frozenset[str] = frozenset(
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
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class WarningInfo:
    """Warning information."""

    warn_type: str = ""
    severity: str = "warning"
    message: str = ""
    file_path: str = ""
    line: int = 0
    node_id: int = 0
    details: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# WarningCollector
# ---------------------------------------------------------------------------


class WarningCollector:
    """Collects warnings progressively during GraphBuilder.build()."""

    def __init__(self) -> None:
        """Initialize the warning collector."""
        self._warnings: list[WarningInfo] = []

    # ------------------------------------------------------------------
    # Add
    # ------------------------------------------------------------------

    def add(
        self,
        warn_type: str,
        severity: str = "warning",
        message: str = "",
        file_path: str = "",
        line: int = 0,
        node_id: int = 0,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Add a warning."""
        if warn_type not in VALID_WARN_TYPES:
            raise ValueError(
                f"Invalid warn type: {warn_type}. Allowed: {sorted(VALID_WARN_TYPES)}"
            )
        self._warnings.append(
            WarningInfo(
                warn_type=warn_type,
                severity=severity,
                message=message,
                file_path=file_path,
                line=line,
                node_id=node_id,
                details=details or {},
            )
        )

    def extend(self, warnings: list[WarningInfo]) -> None:
        """Add multiple warnings."""
        self._warnings.extend(warnings)

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get_all(self) -> list[WarningInfo]:
        """Return a copy of all warnings."""
        return list(self._warnings)

    # ------------------------------------------------------------------
    # Deduplication
    # ------------------------------------------------------------------

    def deduplicate(self) -> None:
        """Remove duplicate warnings in-place."""
        seen: set[tuple[str, str, int]] = set()
        deduped: list[WarningInfo] = []
        for w in self._warnings:
            key = (w.warn_type, os.path.normcase(os.path.normpath(w.file_path)), w.line)
            if key not in seen:
                seen.add(key)
                deduped.append(w)
        self._warnings = deduped

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Detection helpers (called by GraphBuilder)
# ---------------------------------------------------------------------------


def _is_dataclass_field(node: Any, node_id_map: dict[int, Any]) -> bool:
    """Check if a field node belongs to a @dataclass class."""
    if node.node_type != "field" or not node.parent_node_id:
        return False
    parent = node_id_map.get(node.parent_node_id)
    if not parent:
        return False
    for dec in parent.decorators or []:
        if dec == "dataclass" or dec.endswith(".dataclass"):
            return True
    return False


def _node_file_path(node: Any, file_id_to_path: dict[int, Any] | None) -> str:
    """Look up a node's file path."""
    fp = file_id_to_path.get(node.file_id) if file_id_to_path else None
    return fp or ""


def detect_write_only_nodes(
    nodes: list[Any],
    edges: list[Any],
    node_id_map: dict[int, Any] | None = None,
    file_id_to_path: dict[int, Any] | None = None,
) -> list[WarningInfo]:
    """Detect write-only and unused variables."""
    warnings: list[WarningInfo] = []
    if node_id_map is None:
        node_id_map = {}

    node_edges: dict[int, set[Any]] = {}
    for edge in edges:
        node_edges.setdefault(edge.target_id, set()).add(edge.edge_type)

    for node in nodes:
        if node.node_type not in ("variable", "field"):
            continue
        edge_types = node_edges.get(node.id, set())
        fp = _node_file_path(node, file_id_to_path)

        if node.name in _PUBLIC_API_DUNDERS:
            continue

        if node.name == "_":
            continue

        if not edge_types:
            if _is_dataclass_field(node, node_id_map):
                continue
            warnings.append(
                WarningInfo(
                    warn_type="unused_variable",
                    severity="warning",
                    message=f"'{node.name}' is defined but never used",
                    file_path=fp,
                    line=node.line_start,
                    node_id=node.id,
                )
            )
        elif "write" in edge_types and "read" not in edge_types:
            if _is_dataclass_field(node, node_id_map):
                continue
            warnings.append(
                WarningInfo(
                    warn_type="write_only",
                    severity="warning",
                    message=f"'{node.name}' is written but never read",
                    file_path=fp,
                    line=node.line_start,
                    node_id=node.id,
                )
            )

    return warnings


def detect_file_too_large(
    file_path: str, file_size: int, max_size_mb: int
) -> Optional[WarningInfo]:
    """Check if a file exceeds the size limit."""
    max_bytes = max_size_mb * 1024 * 1024
    if file_size > max_bytes:
        return WarningInfo(
            warn_type="file_too_large",
            severity="info",
            message=(
                f"'{file_path}' ({file_size / 1024 / 1024:.1f} MB) "
                f"exceeds max file size ({max_size_mb} MB), skipped"
            ),
            file_path=file_path,
            line=0,
            node_id=0,
        )
    return None

