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

VALID_WARN_TYPES: frozenset[str] = WARN_TYPE_VALUES


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
    public_api_names: frozenset[str] | None = None,
) -> list[WarningInfo]:
    """Detect write-only and unused variables."""
    warnings: list[WarningInfo] = []
    if node_id_map is None:
        node_id_map = {}
    if public_api_names is None:
        public_api_names = frozenset()

    node_edges: dict[int, set[Any]] = {}
    for edge in edges:
        node_edges.setdefault(edge.target_id, set()).add(edge.edge_type)

    for node in nodes:
        if node.node_type not in ("variable", "field"):
            continue
        edge_types = node_edges.get(node.id, set())
        fp = _node_file_path(node, file_id_to_path)

        if node.name in public_api_names:
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

