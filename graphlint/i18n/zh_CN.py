# -*- coding: utf-8 -*-
"""Simplified Chinese string table."""

STRINGS: dict[str, str] = {
    # -------- General --------
    "app.name": "graphlint",
    "app.description": "代码依赖关系图分析工具",
    # -------- CLI query --------
    "cli.query.title": "=== graphlint 分析结果 ===",
    "cli.query.dir": "目录",
    "cli.query.build_time": "构建时间",
    "cli.query.total_summary": (
        "共 {count} 个连通分量，总节点 {nodes} 个，总边 {edges} 个"
    ),
    "cli.query.graph_entry": "入口",
    "cli.query.graph_no_entry": "入口: 未识别",
    "cli.query.graph_dead_code": "疑似死代码",
    "cli.query.graph_nodes": "类/函数节点",
    "cli.query.graph_vars": "变量/字段节点",
    "cli.query.skipped_clean": "已略过 {count} 个无异常的图",
    "cli.query.skipped_oversized": ("已略过 {count} 个图（含 {large} 个大型图）"),
    "cli.query.index_mode": ("输出限制：仅显示索引，使用 -g <id> 查询详情"),
    "cli.query.has_more": "还有更多结果。请使用过滤条件或 -g <id> 查看详情。",
    # -------- CLI detail --------
    "cli.detail.title": "=== 图 #{id} 详情 ===",
    "cli.detail.files": "文件",
    "cli.detail.nodes_title": "节点列表",
    "cli.detail.edges_title": "边列表",
    "cli.detail.warnings_title": "警告",
    "cli.detail.node_count": "节点数: {class_count} 类, {func_count} 函数, {method_count} 方法, {var_count} 变量, {field_count} 字段",
    # -------- Warnings --------
    "warning.unused_import": "{count} 个 import 未使用",
    "warning.dynamic_import": "{count} 个动态导入",
    "warning.circular_ref": "{count} 个循环引用",
    "warning.syntax_error": "{count} 个语法错误",
    "warning.write_only": "{count} 个只写变量",
    "warning.deprecated_usage": "{count} 个弃用函数被调用",
    "warning.dead_code": "{count} 个疑似死代码",
    "warning.type_mismatch": "{count} 个可疑类型声明",
    "warning.unresolved_ref": "{count} 个未解析的引用",
    "warning.unused_variable": "{count} 个未被访问的变量",
    "warning.file_too_large": "{count} 个文件过大",
    # -------- Global stats --------
    "cli.query.global_stats": "全局统计:",
    # -------- Config --------
    "config.not_found": "未找到 .graphlint 元数据目录",
    "config.copied": "配置已从 {source} 复制到 {dest}",
    "config.saved": "配置已保存",
    "config.invalid_key": "无效的配置键: {key}",
    # -------- Help text --------
    "help.description": "代码依赖关系图分析工具",
    "help.subcommands": "子命令",
    "help.query": "查询依赖关系图",
    "help.build": "构建/重建索引",
    "help.install": "将 graphlint 提示词安装到 Agent 工具（opencode, cursor, codex, cc）",
    "help.uninstall": "从 Agent 工具中移除 graphlint 提示词",
    "help.config": "管理配置",
    "help.config.operations": "配置操作",
    "help.config.show": "显示当前配置",
    "help.config.get": "获取配置项",
    "help.config.set": "设置配置项",
    "help.config.copy_from": "从源目录复制配置",
    "help.config.add_entry_rule": "添加入口规则",
    "help.config.remove_entry_rule": "移除入口规则",
    "help.config.add_exclude": "添加排除模式",
    "help.config.remove_exclude": "移除排除模式",
    "help.param.lang": "语言：system / zh_CN / en",
    # -------- Errors --------
    "error.hash_mismatch": "文件哈希不匹配。请先执行 query 或 build 更新索引。",
    "error.no_index": "尚未构建索引。请先执行 build。",
    "error.invalid_graph_id": "图 #{id} 不存在。可用范围: 1-{max}",
    "error.invalid_path": "无效路径: {path}",
    "error.parse_error": "{file} 解析错误: {error}",
    "error.build_failed": "构建失败: {error}",
}
