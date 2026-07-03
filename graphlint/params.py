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
        help="包含测试文件中的引用",
        category="query",
    ),
    ParamDef(
        name="exclude_clean",
        cli_flags=["--exclude-clean", "-C"],
        type=ParamType.FLAG,
        default=False,
        help="排除无异常的图，仅返回包含警告/错误的图",
        category="query",
    ),
    ParamDef(
        name="exclude_unreachable",
        cli_flags=["--reachability", "-R"],
        type=ParamType.FLAG,
        default=False,
        help="仅返回从入口经 CALL 边可达的图（排除不可达死代码）",
        category="query",
    ),
    ParamDef(
        name="dead_code_tests",
        cli_flags=["--dead-code-tests"],
        type=ParamType.FLAG,
        default=False,
        help="查询引用了疑似死代码的测试",
        category="query",
    ),
    ParamDef(
        name="graph_id",
        cli_flags=["--graph-id", "-g"],
        type=ParamType.INT,
        default=None,
        help="查询指定编号图结构的详细信息",
        category="query",
    ),
    ParamDef(
        name="json_output",
        cli_flags=["--json", "-j"],
        type=ParamType.FLAG,
        default=False,
        help="以结构化 JSON 格式返回",
        category="query",
    ),
    ParamDef(
        name="path_format",
        cli_flags=["--path-format", "-p"],
        type=ParamType.CHOICE,
        default="relative",
        choices=["absolute", "relative"],
        help="路径格式：absolute / relative",
        category="query",
    ),
    ParamDef(
        name="root_dir",
        cli_flags=["--root-dir", "-r"],
        type=ParamType.STR,
        default=".",
        help="指定目标根目录（元数据目录的父目录）",
        category="query",
    ),
    ParamDef(
        name="max_results",
        cli_flags=["--max-results", "-n"],
        type=ParamType.INT,
        default=50,
        help="最大返回图数量（1–1000）",
        category="query",
    ),
    ParamDef(
        name="min_nodes",
        cli_flags=["--min-nodes"],
        type=ParamType.INT,
        default=0,
        help="仅返回节点数 ≥ N 的图",
        category="query",
    ),
    ParamDef(
        name="max_nodes",
        cli_flags=["--max-nodes"],
        type=ParamType.INT,
        default=None,
        help="仅返回节点数 ≤ N 的图",
        category="query",
    ),
    ParamDef(
        name="warn_types",
        cli_flags=["--warn-types", "-w"],
        type=ParamType.STR,
        default=None,
        help="逗号分隔的警告类型过滤",
        category="query",
    ),
    ParamDef(
        name="sort_by",
        cli_flags=["--sort-by"],
        type=ParamType.CHOICE,
        default="warnings",
        choices=["warnings", "nodes", "edges", "name"],
        help="排序方式：warnings / nodes / edges / name",
        category="query",
    ),
    ParamDef(
        name="detail_level",
        cli_flags=["--detail", "-d"],
        type=ParamType.CHOICE,
        default="auto",
        choices=["auto", "summary", "full", "minimal"],
        help="详细级别：auto / summary / full / minimal",
        category="query",
    ),
    ParamDef(
        name="output_limit",
        cli_flags=["--output-limit"],
        type=ParamType.INT,
        default=8000,
        help="输出文本量上限（字符数，100–100000）",
        category="query",
    ),
    ParamDef(
        name="edge_limit",
        cli_flags=["--edge-limit"],
        type=ParamType.INT,
        default=10,
        help="单图详情最大显示的边数（0=不限制）",
        category="query",
    ),
    ParamDef(
        name="file_limit",
        cli_flags=["--file-limit"],
        type=ParamType.INT,
        default=10,
        help="单图详情最大显示的文件数（0=不限制）",
        category="query",
    ),
    ParamDef(
        name="node_limit",
        cli_flags=["--node-limit"],
        type=ParamType.INT,
        default=30,
        help="单图详情最大显示的节点数（0=不限制）",
        category="query",
    ),
    ParamDef(
        name="no_scan",
        cli_flags=["--no-scan"],
        type=ParamType.FLAG,
        default=False,
        help="仅从已有索引查询，不自动扫描/构建",
        category="query",
    ),
    # -------- Build parameters --------
    ParamDef(
        name="force_rebuild",
        cli_flags=["--force", "-f"],
        type=ParamType.FLAG,
        default=False,
        help="强制全量重建索引（忽略增量）",
        category="build",
    ),
    ParamDef(
        name="parallel",
        cli_flags=["--parallel", "-P"],
        type=ParamType.INT,
        default=0,
        help="并行 worker 数（0=自动检测 CPU 核心数，最大 64）",
        category="build",
    ),
    # -------- Config parameters --------
    ParamDef(
        name="lang",
        cli_flags=["--lang"],
        type=ParamType.CHOICE,
        default="system",
        choices=["system", "zh_CN", "en"],
        help="语言：system / zh_CN / en",
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
        help="配置操作",
        category="config",
    ),
    ParamDef(
        name="config_key",
        cli_flags=["--key"],
        type=ParamType.STR,
        default=None,
        help="配置键（用于 set/get）",
        category="config",
    ),
    ParamDef(
        name="config_value",
        cli_flags=["--value"],
        type=ParamType.STR,
        default=None,
        help="配置值（用于 set）",
        category="config",
    ),
    ParamDef(
        name="config_source",
        cli_flags=["--from"],
        type=ParamType.STR,
        default=None,
        help="复制配置的源目录（用于 copy-from）",
        category="config",
    ),
    ParamDef(
        name="rule_json",
        cli_flags=["--rule-json"],
        type=ParamType.STR,
        default=None,
        help="add-entry-rule 的 JSON 规则字符串",
        category="config",
    ),
    ParamDef(
        name="rule_name",
        cli_flags=["--name"],
        type=ParamType.STR,
        default=None,
        help="remove-entry-rule 的规则名称",
        category="config",
    ),
    ParamDef(
        name="exclude_pattern",
        cli_flags=["--exclude-pattern"],
        type=ParamType.STR,
        default=None,
        help="add-exclude / remove-exclude 的模式",
        category="config",
    ),
]
