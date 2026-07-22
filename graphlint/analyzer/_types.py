# -*- coding: utf-8 -*-
"""Shared types for graph construction."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Optional


@dataclass
class NodeInfo:
    """AST node information."""

    id: int = 0
    file_id: int = 0
    name: str = ""
    qualified_name: str = ""
    node_type: str = ""
    line_start: int = 0
    line_end: int = 0
    col_offset: int = 0
    parent_node_id: int = 0
    is_deprecated: bool = False
    deprecation_msg: str = ""
    type_annotation: str = ""
    is_async: bool = False
    decorators: List[str] = field(default_factory=list)
    docstring: str = ""
    is_entry: bool = False


@dataclass
class ParseResult:
    """Parse result for a single file."""

    file_path: str = ""
    nodes: List[NodeInfo] = field(default_factory=list)
    imports: list[Any] = field(default_factory=list)
    name_usages: set[str] = field(default_factory=set)
    warnings: list[Any] = field(default_factory=list)
    hash: str = ""
    source: Optional[str] = None
    tree: Optional[Any] = None  # Language-specific AST (e.g. ast.Module for Python)
    references: list[ReferenceInfo] = field(default_factory=list)


@dataclass
class ReferenceInfo:
    """A structured reference collected during AST parse."""

    source_qname: str = ""
    target_name: str = ""
    edge_type: str = ""
    line: int = 0


@dataclass
class EdgeInfo:
    """Edge information."""

    source_id: int = 0
    target_id: int = 0
    edge_type: str = ""
    file_id: int = 0
    line: int = 0
    context: str = ""


@dataclass
class ComponentInfo:
    """Connected component information."""

    component_id: int = 0
    node_ids: set[int] = field(default_factory=set)
    entry_info: list[Any] = field(default_factory=list)
    is_dead_code: bool = False
    is_unreachable: bool = False


@dataclass
class EntryInfo:
    """Entry point information."""

    rule_name: str = ""
    file_path: str = ""
    line: int = 0
    node_id: int = 0
    description: str = ""
    no_propagate: bool = False


@dataclass
class GraphBuildResult:
    """Complete output of GraphBuilder.build()."""

    nodes: list[NodeInfo] = field(default_factory=list)
    edges: list[EdgeInfo] = field(default_factory=list)
    warnings: list[Any] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    files_data: dict[str, ParseResult] = field(default_factory=dict)
    entry_info_list: list[EntryInfo] = field(default_factory=list)
    component_map: dict[int, int] = field(default_factory=dict)
    components: list[ComponentInfo] = field(default_factory=list)
    node_id_map: dict[int, Any] = field(default_factory=dict)
