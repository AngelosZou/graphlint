# -*- coding: utf-8 -*-
"""English string table."""

STRINGS: dict[str, str] = {
    # -------- General --------
    "app.name": "graphlint",
    "app.description": "Code Dependency Graph Analyzer",
    # -------- CLI query --------
    "cli.query.title": "=== graphlint Analysis Results ===",
    "cli.query.dir": "Directory",
    "cli.query.build_time": "Build time",
    "cli.query.total_summary": "{count} components, {nodes} nodes, {edges} edges total",
    "cli.query.graph_entry": "Entry:",
    "cli.query.graph_no_entry": "Entry: unrecognized",
    "cli.query.graph_dead_code": "suspected dead code",
    "cli.query.graph_nodes": "Class/Function nodes",
    "cli.query.graph_vars": "Variable/Field nodes",
    "cli.query.skipped_clean": "Skipped {count} clean graphs",
    "cli.query.skipped_oversized": "Skipped {count} graphs ({large} large)",
    "cli.query.index_mode": (
        "Output limited: showing index only, use -g <id> for details"
    ),
    "cli.query.has_more": "More results available. Use filters or -g <id> for details.",
    # -------- CLI detail --------
    "cli.detail.title": "=== Graph #{id} Details ===",
    "cli.detail.files": "Files",
    "cli.detail.nodes_title": "Node List",
    "cli.detail.edges_title": "Edge List",
    "cli.detail.warnings_title": "Warnings",
    "cli.detail.node_count": "Node count: {class_count} classes, {func_count} functions, {method_count} methods, {var_count} variables, {field_count} fields",
    # -------- Warnings --------
    "warning.unused_import": "{count} unused imports",
    "warning.dynamic_import": "{count} dynamic imports",
    "warning.circular_ref": "{count} circular references",
    "warning.syntax_error": "{count} syntax errors",
    "warning.write_only": "{count} write-only variables",
    "warning.deprecated_usage": "{count} deprecated usages",
    "warning.dead_code": "{count} dead code suspects",
    "warning.type_mismatch": "{count} suspicious type declarations",
    "warning.unresolved_ref": "{count} unresolved references",
    "warning.unused_variable": "{count} unused variables",
    "warning.file_too_large": "{count} files too large",
    # -------- Global stats --------
    "cli.query.global_stats": "Global Statistics:",
    # -------- Config --------
    "config.not_found": "Metadata directory .graphlint not found",
    "config.copied": "Configuration copied from {source} to {dest}",
    "config.saved": "Configuration saved",
    "config.invalid_key": "Invalid configuration key: {key}",
    # -------- Help text --------
    "help.description": "Code Dependency Graph Analyzer",
    "help.subcommands": "Subcommands",
    "help.query": "Query dependency graph",
    "help.build": "Build/rebuild index",
    "help.install": "Install graphlint prompt into agent tools (opencode, cursor, codex, cc)",
    "help.uninstall": "Remove graphlint prompt from agent tools",
    "help.config": "Manage configuration",
    "help.config.operations": "Config operations",
    "help.config.show": "Show current configuration",
    "help.config.get": "Get config item",
    "help.config.set": "Set config item",
    "help.config.copy_from": "Copy config from source directory",
    "help.config.add_entry_rule": "Add entry rule",
    "help.config.remove_entry_rule": "Remove entry rule",
    "help.config.add_exclude": "Add exclude pattern",
    "help.config.remove_exclude": "Remove exclude pattern",
    "help.param.lang": "Language: system / zh_CN / en",
    # -------- Errors --------
    "error.hash_mismatch": "File hash mismatch. Run query or build first.",
    "error.no_index": "No index found. Run build first.",
    "error.invalid_graph_id": "Graph #{id} not found. Range: 1-{max}",
    "error.invalid_path": "Invalid path: {path}",
    "error.parse_error": "Parse error in {file}: {error}",
    "error.build_failed": "Build failed: {error}",
}
