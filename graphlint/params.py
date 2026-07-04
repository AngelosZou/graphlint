# -*- coding: utf-8 -*-
"""Single source of parameter definitions for CLI and Python API."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, List, Optional


class ParamType(Enum):
    """Parameter type enum."""

    STR = "str"
    INT = "int"
    BOOL = "bool"
    CHOICE = "choice"
    FLAG = "flag"


@dataclass
class ParamDef:
    """Parameter definition data class."""

    name: str
    cli_flags: List[str]
    type: ParamType
    default: Any
    help: str
    help_key: str = ""
    choices: Optional[List[str]] = None
    cli_only: bool = False
    api_only: bool = False
    category: str = "query"


# ---------------------------------------------------------------------------
# Whitelist sets (for parameter validation)
# ---------------------------------------------------------------------------

VALID_WARN_TYPES: frozenset[str] = frozenset(
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

VALID_SORT_BY: frozenset[str] = frozenset({"warnings", "nodes", "edges", "name"})


# ---------------------------------------------------------------------------
# Parameter definition list (single source)
# ---------------------------------------------------------------------------

PARAM_DEFS: List[ParamDef] = [
    # -------- Query parameters --------
    ParamDef(
        name="include_tests",
        cli_flags=["--include-tests", "-t"],
        type=ParamType.FLAG,
        default=False,
        help="Include references in test files",
        help_key="help.param.include_tests",
        category="query",
    ),
    ParamDef(
        name="exclude_clean",
        cli_flags=["--exclude-clean", "-C"],
        type=ParamType.FLAG,
        default=False,
        help="Exclude clean graphs, return only those with warnings/errors",
        help_key="help.param.exclude_clean",
        category="query",
    ),
    ParamDef(
        name="exclude_unreachable",
        cli_flags=["--reachability", "-R"],
        type=ParamType.FLAG,
        default=False,
        help="Return only graphs reachable from entry points via CALL edges",
        help_key="help.param.exclude_unreachable",
        category="query",
    ),
    ParamDef(
        name="dead_code_tests",
        cli_flags=["--dead-code-tests"],
        type=ParamType.FLAG,
        default=False,
        help="Query tests referencing suspected dead code",
        help_key="help.param.dead_code_tests",
        category="query",
    ),
    ParamDef(
        name="graph_id",
        cli_flags=["--graph-id", "-g"],
        type=ParamType.INT,
        default=None,
        help="Show detailed info for a specific graph by ID",
        help_key="help.param.graph_id",
        category="query",
    ),
    ParamDef(
        name="json_output",
        cli_flags=["--json", "-j"],
        type=ParamType.FLAG,
        default=False,
        help="Return output in structured JSON format",
        help_key="help.param.json_output",
        category="query",
    ),
    ParamDef(
        name="path_format",
        cli_flags=["--path-format", "-p"],
        type=ParamType.CHOICE,
        default="relative",
        choices=["absolute", "relative"],
        help="Path format: absolute / relative",
        help_key="help.param.path_format",
        category="query",
    ),
    ParamDef(
        name="root_dir",
        cli_flags=["--root-dir", "-r"],
        type=ParamType.STR,
        default=".",
        help="Target root directory (parent of metadata dir)",
        help_key="help.param.root_dir",
        category="query",
    ),
    ParamDef(
        name="max_results",
        cli_flags=["--max-results", "-n"],
        type=ParamType.INT,
        default=50,
        help="Max number of graphs to return (1–1000)",
        help_key="help.param.max_results",
        category="query",
    ),
    ParamDef(
        name="min_nodes",
        cli_flags=["--min-nodes"],
        type=ParamType.INT,
        default=0,
        help="Only return graphs with node count ≥ N",
        help_key="help.param.min_nodes",
        category="query",
    ),
    ParamDef(
        name="max_nodes",
        cli_flags=["--max-nodes"],
        type=ParamType.INT,
        default=None,
        help="Only return graphs with node count ≤ N",
        help_key="help.param.max_nodes",
        category="query",
    ),
    ParamDef(
        name="warn_types",
        cli_flags=["--warn-types", "-w"],
        type=ParamType.STR,
        default=None,
        help="Comma-separated list of warning types to filter",
        help_key="help.param.warn_types",
        category="query",
    ),
    ParamDef(
        name="sort_by",
        cli_flags=["--sort-by"],
        type=ParamType.CHOICE,
        default="warnings",
        choices=["warnings", "nodes", "edges", "name"],
        help="Sort by: warnings / nodes / edges / name",
        help_key="help.param.sort_by",
        category="query",
    ),
    ParamDef(
        name="detail_level",
        cli_flags=["--detail", "-d"],
        type=ParamType.CHOICE,
        default="auto",
        choices=["auto", "summary", "full", "minimal"],
        help="Detail level: auto / summary / full / minimal",
        help_key="help.param.detail_level",
        category="query",
    ),
    ParamDef(
        name="output_limit",
        cli_flags=["--output-limit"],
        type=ParamType.INT,
        default=8000,
        help="Output character limit (100–100000)",
        help_key="help.param.output_limit",
        category="query",
    ),
    ParamDef(
        name="edge_limit",
        cli_flags=["--edge-limit"],
        type=ParamType.INT,
        default=10,
        help="Max edges shown in detail view (0=unlimited)",
        help_key="help.param.edge_limit",
        category="query",
    ),
    ParamDef(
        name="file_limit",
        cli_flags=["--file-limit"],
        type=ParamType.INT,
        default=10,
        help="Max files shown in detail view (0=unlimited)",
        help_key="help.param.file_limit",
        category="query",
    ),
    ParamDef(
        name="node_limit",
        cli_flags=["--node-limit"],
        type=ParamType.INT,
        default=30,
        help="Max nodes shown in detail view (0=unlimited)",
        help_key="help.param.node_limit",
        category="query",
    ),
    ParamDef(
        name="no_scan",
        cli_flags=["--no-scan"],
        type=ParamType.FLAG,
        default=False,
        help="Query from existing index only, skip auto scan/build",
        help_key="help.param.no_scan",
        category="query",
    ),
    # -------- Build parameters --------
    ParamDef(
        name="force_rebuild",
        cli_flags=["--force", "-f"],
        type=ParamType.FLAG,
        default=False,
        help="Force full index rebuild (ignore incremental)",
        help_key="help.param.force_rebuild",
        category="build",
    ),
    ParamDef(
        name="parallel",
        cli_flags=["--parallel", "-P"],
        type=ParamType.INT,
        default=0,
        help="Parallel workers (0=auto-detect CPU count, max 64)",
        help_key="help.param.parallel",
        category="build",
    ),
    # -------- Config parameters --------
    ParamDef(
        name="lang",
        cli_flags=["--lang"],
        type=ParamType.CHOICE,
        default="system",
        choices=["system", "zh_CN", "en"],
        help="Language: system / zh_CN / en",
        help_key="help.param.lang",
        category="config",
    ),
    ParamDef(
        name="config_action",
        cli_flags=["--config"],
        type=ParamType.CHOICE,
        default=None,
        choices=[
            "show",
            "set",
            "get",
            "copy-from",
            "add-entry-rule",
            "remove-entry-rule",
            "add-exclude",
            "remove-exclude",
        ],
        help="Configuration action",
        help_key="help.param.config_action",
        category="config",
    ),
    ParamDef(
        name="config_key",
        cli_flags=["--key"],
        type=ParamType.STR,
        default=None,
        help="Config key (for set/get)",
        help_key="help.param.config_key",
        category="config",
    ),
    ParamDef(
        name="config_value",
        cli_flags=["--value"],
        type=ParamType.STR,
        default=None,
        help="Config value (for set)",
        help_key="help.param.config_value",
        category="config",
    ),
    ParamDef(
        name="config_source",
        cli_flags=["--from"],
        type=ParamType.STR,
        default=None,
        help="Source directory for copy-from",
        help_key="help.param.config_source",
        category="config",
    ),
    ParamDef(
        name="rule_json",
        cli_flags=["--rule-json"],
        type=ParamType.STR,
        default=None,
        help="JSON rule string for add-entry-rule",
        help_key="help.param.rule_json",
        category="config",
    ),
    ParamDef(
        name="rule_name",
        cli_flags=["--name"],
        type=ParamType.STR,
        default=None,
        help="Rule name for remove-entry-rule",
        help_key="help.param.rule_name",
        category="config",
    ),
    ParamDef(
        name="exclude_pattern",
        cli_flags=["--exclude-pattern"],
        type=ParamType.STR,
        default=None,
        help="Pattern for add-exclude / remove-exclude",
        help_key="help.param.exclude_pattern",
        category="config",
    ),
]
