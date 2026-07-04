# -*- coding: utf-8 -*-
"""Output formatter — text and JSON formats."""

from __future__ import annotations

import os
from typing import Any

from graphlint.i18n import I18nManager
from graphlint.query.engine import (
    GraphDetail,
    GraphSummary,
    QueryResult,
)
from graphlint.query.volume import OutputPlan


class TextFormatter:
    """Human-readable text formatter."""

    def __init__(
        self,
        i18n: I18nManager,
        path_format: str = "relative",
        root_dir: str = ".",
    ) -> None:
        self.i18n = i18n
        self.path_format = path_format
        self.root_dir = os.path.realpath(root_dir)

    def format_query_result(
        self,
        result: QueryResult,
        plan: OutputPlan,
    ) -> str:
        """Format query result according to OutputPlan."""
        if plan.mode == "full":
            return self._format_full(result, plan)
        elif plan.mode == "index":
            return self._format_index(result)
        else:
            return self._format_truncated(result, plan)

    def _format_full(self, result: QueryResult, plan: OutputPlan) -> str:
        """Full mode output."""
        lines = [self.i18n.t("cli.query.title"), ""]
        lines.append(f"{self.i18n.t('cli.query.dir')}: {self.root_dir}")

        total_nodes = sum(g.node_count + g.variable_count for g in result.graphs)
        total_edges = sum(g.edge_count for g in result.graphs)
        lines.append(
            self.i18n.t(
                "cli.query.total_summary",
                count=result.total_graphs,
                nodes=total_nodes,
                edges=total_edges,
            )
        )
        lines.append("")

        for g in result.graphs:
            lines.extend(self._graph_block(g))

        if result.skipped_clean > 0:
            lines.append(
                self.i18n.t("cli.query.skipped_clean", count=result.skipped_clean)
            )
        if result.skipped_oversized > 0:
            lines.append(
                self.i18n.t(
                    "cli.query.skipped_oversized",
                    count=result.skipped_oversized,
                    large=0,
                )
            )
        if result.has_more:
            lines.append(self.i18n.t("cli.query.has_more"))

        lines.append("")
        lines.append(self.i18n.t("cli.query.global_stats"))
        for wt, cnt in sorted(result.warnings_summary.items()):
            if cnt > 0:
                key = f"warning.{wt}"
                lines.append(f"  {self.i18n.t(key, count=cnt)}")

        return "\n".join(lines)

    def _graph_block(self, g: GraphSummary) -> list[str]:
        """Text block for a single graph."""
        lines = []
        entry_label = (
            self.i18n.t("cli.query.graph_entry")
            if g.entry_file
            else self.i18n.t("cli.query.graph_no_entry")
        )
        entry_str = f"{entry_label} {self._resolve_path(g.entry_file)}"
        if g.entry_line:
            entry_str += f" line {g.entry_line}"
        if g.entry:
            entry_str += f" — {g.entry}"

        dead = ""
        if g.is_dead_code:
            dead = f" [{self.i18n.t('cli.query.graph_dead_code')}]"
        elif g.is_unreachable:
            dead = " [unreachable]"

        lines.append(f"graph{g.graph_id}: {entry_str}{dead}")
        lines.append(
            f"  {self.i18n.t('cli.query.graph_nodes')}: {g.node_count}, "
            f"{self.i18n.t('cli.query.graph_vars')}: {g.variable_count}"
        )
        if g.warnings:
            lines.append(f"  ⚠ {', '.join(g.warnings)}")
        lines.append("")
        return lines

    def _format_index(self, result: QueryResult) -> str:
        """Index mode output."""
        lines = [
            self.i18n.t("cli.query.title"),
            "",
            f"{self.i18n.t('cli.query.dir')}: {self.root_dir}",
            self.i18n.t("cli.query.index_mode"),
            "",
        ]
        for g in result.graphs:
            entry = g.entry or g.entry_file or self.i18n.t("cli.query.graph_no_entry")
            suffix = " ☠" if g.is_dead_code else " ⚡" if g.is_unreachable else ""
            wc = len(g.warnings)
            lines.append(
                f"[{g.graph_id:>3}] {entry}{suffix}    "
                f"nodes:{g.node_count + g.variable_count}  "
                f"edges:{g.edge_count}  ⚠{wc}"
            )
        if result.has_more:
            lines.append(self.i18n.t("cli.query.has_more"))
        return "\n".join(lines)

    def _format_truncated(self, result: QueryResult, plan: OutputPlan) -> str:
        """Truncated mode output."""
        text = self._format_full(result, plan)
        if plan.skipped_count > 0:
            text += "\n" + self.i18n.t(
                "cli.query.skipped_oversized",
                count=plan.skipped_count,
                large=plan.skipped_large_count,
            )
        return text

    def format_graph_detail(
        self,
        detail: GraphDetail,
        edge_limit: int = 10,
        file_limit: int = 10,
        node_limit: int = 30,
    ) -> str:
        """Single graph detail output."""
        lines = [self.i18n.t("cli.detail.title", id=detail.graph_id), ""]
        lines.append(f"{self.i18n.t('cli.query.graph_entry')} {detail.entry}")

        shown_files = detail.files[:file_limit] if file_limit > 0 else detail.files
        lines.append(f"{self.i18n.t('cli.detail.files')}: {', '.join(shown_files)}")
        omitted_files = len(detail.files) - len(shown_files)
        if omitted_files > 0:
            lines.append(f"  ... and {omitted_files} more files (use --file-limit N)")

        class_c = sum(1 for n in detail.nodes if n.node_type == "class")
        func_c = sum(1 for n in detail.nodes if n.node_type == "function")
        meth_c = sum(1 for n in detail.nodes if n.node_type == "method")
        var_c = sum(1 for n in detail.nodes if n.node_type == "variable")
        field_c = sum(1 for n in detail.nodes if n.node_type == "field")
        lines.append(
            self.i18n.t(
                "cli.detail.node_count",
                class_count=class_c,
                func_count=func_c,
                method_count=meth_c,
                var_count=var_c,
                field_count=field_c,
            )
        )
        lines.append("")
        lines.append(self.i18n.t("cli.detail.nodes_title") + ":")
        shown_nodes = detail.nodes[:node_limit] if node_limit > 0 else detail.nodes
        for n in shown_nodes:
            entry_mark = (
                " (entry)"
                if hasattr(n, "is_entry") and getattr(n, "is_entry", False)
                else ""
            )
            lines.append(
                f"  [N{n.node_id:04d}] {n.node_type} {n.name}  "
                f"{self._resolve_path(n.file_path)}:{n.line_start}{entry_mark}"
            )
        omitted_nodes = len(detail.nodes) - len(shown_nodes)
        if omitted_nodes > 0:
            lines.append(f"  ... and {omitted_nodes} more nodes (use --node-limit N)")
        lines.append("")
        lines.append(self.i18n.t("cli.detail.edges_title") + ":")
        shown_edges = detail.edges[:edge_limit] if edge_limit > 0 else detail.edges
        for e in shown_edges:
            lines.append(
                f"  [E] {e.source_name} --[{e.edge_type}]--> {e.target_name}  "
                f"{self._resolve_path(e.file_path)}:{e.line}"
            )
        omitted_edges = len(detail.edges) - len(shown_edges)
        if omitted_edges > 0:
            lines.append(f"  ... and {omitted_edges} more edges (use --edge-limit N)")
        lines.append("")
        lines.append(self.i18n.t("cli.detail.warnings_title") + ":")
        for w in detail.warnings:
            lines.append(
                f"  [{w.warn_type}] {w.message}  "
                f"{self._resolve_path(w.file_path or '')}:{w.line or ''}"
            )
        return "\n".join(lines)

    def format_json(
        self,
        result: QueryResult,
        root_dir: str,
        elapsed_ms: int,
    ) -> dict[str, Any]:
        """JSON format output."""
        graphs_json = []
        for g in result.graphs:
            graphs_json.append(
                {
                    "graph_id": g.graph_id,
                    "entry": g.entry,
                    "entry_file": g.entry_file,
                    "entry_line": g.entry_line,
                    "node_count": g.node_count,
                    "variable_count": g.variable_count,
                    "edge_count": g.edge_count,
                    "warnings": g.warnings,
                    "is_dead_code": g.is_dead_code,
                    "is_unreachable": g.is_unreachable,
                    "component_size": g.component_size,
                }
            )
        return {
            "status": "ok",
            "query_time_ms": elapsed_ms,
            "root_dir": root_dir,
            "path_format": self.path_format,
            "result": {
                "graphs": graphs_json,
                "total_graphs": result.total_graphs,
                "skipped_clean": result.skipped_clean,
                "skipped_oversized": result.skipped_oversized,
                "has_more": result.has_more,
                "warnings_summary": result.warnings_summary,
            },
        }

    def format_json_detail(
        self,
        detail: GraphDetail,
        elapsed_ms: int,
        edge_limit: int = 10,
        file_limit: int = 10,
        node_limit: int = 30,
    ) -> dict[str, Any]:
        """JSON format single graph detail."""
        shown_edges = detail.edges[:edge_limit] if edge_limit > 0 else detail.edges
        shown_nodes = detail.nodes[:node_limit] if node_limit > 0 else detail.nodes
        shown_files = detail.files[:file_limit] if file_limit > 0 else detail.files
        result: dict[str, Any] = {
            "status": "ok",
            "query_time_ms": elapsed_ms,
            "root_dir": self.root_dir,
            "graph": {
                "graph_id": detail.graph_id,
                "entry": detail.entry,
                "files": shown_files,
                "nodes": [
                    {
                        "node_id": n.node_id,
                        "name": n.name,
                        "qualified_name": n.qualified_name,
                        "node_type": n.node_type,
                        "file_path": n.file_path,
                        "line_start": n.line_start,
                        "line_end": n.line_end,
                        "is_deprecated": n.is_deprecated,
                        "type_annotation": n.type_annotation,
                        "decorators": n.decorators,
                    }
                    for n in shown_nodes
                ],
                "edges": [
                    {
                        "source_name": e.source_name,
                        "target_name": e.target_name,
                        "edge_type": e.edge_type,
                        "file_path": e.file_path,
                        "line": e.line,
                    }
                    for e in shown_edges
                ],
                "warnings": [
                    {
                        "warn_type": w.warn_type,
                        "severity": w.severity,
                        "message": w.message,
                        "file_path": w.file_path,
                        "line": w.line,
                    }
                    for w in detail.warnings
                ],
            },
        }
        omitted_edges = len(detail.edges) - len(shown_edges)
        if omitted_edges > 0:
            result["graph"]["edges_omitted"] = omitted_edges
        omitted_nodes = len(detail.nodes) - len(shown_nodes)
        if omitted_nodes > 0:
            result["graph"]["nodes_omitted"] = omitted_nodes
        omitted_files = len(detail.files) - len(shown_files)
        if omitted_files > 0:
            result["graph"]["files_omitted"] = omitted_files
        return result

    def _resolve_path(self, file_path: str) -> str:
        """Resolve path according to path_format."""
        if not file_path:
            return ""
        if self.path_format == "absolute":
            return os.path.normpath(os.path.join(self.root_dir, file_path))
        return file_path
