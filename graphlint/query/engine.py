# -*- coding: utf-8 -*-
"""Query engine — SQLite graph queries, filtering, pagination."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Optional

from contextlib import contextmanager

from graphlint.storage.db import Database


@contextmanager
def _nullcontext() -> Any:
    """No-op transaction context manager."""
    yield


@dataclass
class QueryFilters:
    """Query filter parameters."""

    include_tests: bool = False
    exclude_clean: bool = False
    exclude_unreachable: bool = False
    min_nodes: int = 0
    max_nodes: Optional[int] = None
    warn_types: Optional[list[str]] = None
    sort_by: str = "warnings"
    max_results: int = 50
    graph_id: Optional[int] = None
    dead_code_tests: bool = False


@dataclass
class GraphSummary:
    """Graph summary information."""

    graph_id: int = 0
    entry: str = ""
    entry_file: str = ""
    entry_line: Optional[int] = None
    node_count: int = 0
    variable_count: int = 0
    edge_count: int = 0
    warnings: list[str] = field(default_factory=list)
    is_dead_code: bool = False
    is_unreachable: bool = True
    component_size: int = 0


@dataclass
class NodeDetail:
    """Node detail."""

    node_id: int = 0
    name: str = ""
    qualified_name: str = ""
    node_type: str = ""
    file_path: str = ""
    line_start: int = 0
    line_end: int = 0
    is_deprecated: bool = False
    type_annotation: Optional[str] = None
    decorators: list[str] = field(default_factory=list)


@dataclass
class EdgeDetail:
    """Edge detail."""

    source_name: str = ""
    target_name: str = ""
    edge_type: str = ""
    file_path: str = ""
    line: int = 0


@dataclass
class WarningDetail:
    """Warning detail."""

    warn_type: str = ""
    severity: str = ""
    message: str = ""
    file_path: Optional[str] = None
    line: Optional[int] = None


@dataclass
class GraphDetail:
    """Single graph detail."""

    graph_id: int = 0
    entry: str = ""
    nodes: list[NodeDetail] = field(default_factory=list)
    edges: list[EdgeDetail] = field(default_factory=list)
    warnings: list[WarningDetail] = field(default_factory=list)
    files: list[str] = field(default_factory=list)


@dataclass
class QueryResult:
    """Query result."""

    graphs: list[GraphSummary] = field(default_factory=list)
    total_graphs: int = 0
    skipped_clean: int = 0
    skipped_oversized: int = 0
    has_more: bool = False
    warnings_summary: dict[str, int] = field(default_factory=dict)


@dataclass
class TestDeadCodeRef:
    """Dead code test reference."""

    test_file: str = ""
    line: int = 0
    referenced_symbol: str = ""
    dead_graph_id: int = 0


class QueryEngine:
    """SQLite query engine."""

    _SORT_WHITELIST = {
        "warnings": "warning_count",
        "nodes": "node_count",
        "edges": "edge_count",
        "name": "entry_file",
    }

    def __init__(self, db_path: str, root_dir: str) -> None:
        """Initialize the query engine."""
        if isinstance(db_path, Database):
            self.db = db_path
        elif hasattr(db_path, "execute"):
            # Wrap connected sqlite3.Connection as Database-compatible object
            import types

            conn = db_path
            _db = types.SimpleNamespace()
            _db.conn = conn
            _db.execute = conn.execute
            _db.fetchone = lambda sql, p=(): conn.execute(sql, p).fetchone()
            _db.fetchall = lambda sql, p=(): conn.execute(sql, p).fetchall()
            _db.close = lambda: None
            _db.transaction = lambda: _nullcontext()
            _db.begin_transaction = lambda: None
            _db.commit = lambda: None
            _db.rollback = lambda: None
            self.db = _db  # type: ignore[assignment]
        else:
            self.db = Database(root_dir)  # type: ignore[assignment]
        self.root_dir = root_dir
        self._warn_summary_cache: Optional[dict[str, int]] = None

    def list_graphs(self, filters: QueryFilters) -> QueryResult:
        """List graph summaries with filtering, sorting, pagination."""
        where: list[str] = []
        params: list[Any] = []

        if filters.exclude_clean:
            where.append("warning_count > 0")
        if filters.min_nodes > 0:
            where.append("(node_count + variable_count) >= ?")
            params.append(filters.min_nodes)
        if filters.max_nodes is not None:
            where.append("(node_count + variable_count) <= ?")
            params.append(filters.max_nodes)
        if not filters.include_tests:
            where.append(
                "(gs.entry_file IS NULL OR NOT EXISTS "
                "(SELECT 1 FROM files f WHERE f.path=gs.entry_file AND f.is_test=1))"
            )
        if filters.exclude_unreachable:
            where.append("is_unreachable=0")
        if filters.warn_types:
            for wt in filters.warn_types:
                where.append(
                    "EXISTS (SELECT 1 FROM warnings w "
                    "JOIN nodes n ON w.node_id=n.id "
                    "WHERE w.warn_type=? AND "
                    "n.id IN (SELECT value FROM json_each(gs.root_node_ids)))"
                )
                params.append(wt)

        where_clause = ("WHERE " + " AND ".join(where)) if where else ""
        sort_col = self._SORT_WHITELIST.get(filters.sort_by, "warning_count")

        sql = (
            f"SELECT * FROM graph_snapshots gs {where_clause} "
            f"ORDER BY {sort_col} DESC LIMIT ?"
        )
        params.append(filters.max_results + 1)

        rows = self.db.fetchall(sql, tuple(params))
        has_more = len(rows) > filters.max_results
        rows = rows[: filters.max_results]

        graphs = []
        skipped_clean = 0
        for row in rows:
            gs = self._row_to_summary(row)
            graphs.append(gs)
            if row["warning_count"] == 0:
                skipped_clean += 1

        # Global statistics (use cache to avoid scanning warnings table on every list_graphs call)
        if self._warn_summary_cache is None:
            self._warn_summary_cache = {}
            all_warns = self.db.fetchall(
                "SELECT warn_type, COUNT(*) as cnt FROM warnings GROUP BY warn_type"
            )
            for r in all_warns:
                self._warn_summary_cache[r["warn_type"]] = r["cnt"]
        warn_summary = dict(self._warn_summary_cache)  # Shallow copy for backward compatibility

        return QueryResult(
            graphs=graphs,
            total_graphs=len(rows),
            skipped_clean=skipped_clean,
            skipped_oversized=0,
            has_more=has_more,
            warnings_summary=warn_summary,
        )

    def get_graph_detail(self, graph_id: int) -> Optional[GraphDetail]:
        """Query full details for a specific graph."""
        snap = self.db.fetchone("SELECT * FROM graph_snapshots WHERE id=?", (graph_id,))
        if not snap:
            return None
        root_ids = json.loads(snap["root_node_ids"] or "[]")
        if not root_ids:
            return None

        nid_set, node_rows = self._expand_component(json.dumps(root_ids))
        if not node_rows:
            return None

        details = self._build_node_details(node_rows)
        edge_details = self._build_edge_details(nid_set)
        warn_details = self._build_warn_details(nid_set)
        files = sorted({d.file_path for d in details if d.file_path})

        entry_desc = snap["entry_file"] or ""
        if snap["entry_type"]:
            entry_desc += f" ({snap['entry_type']})"

        return GraphDetail(
            graph_id=graph_id,
            entry=entry_desc,
            nodes=details,
            edges=edge_details,
            warnings=warn_details,
            files=files,
        )

    def _expand_component(self, root_json: str) -> tuple[set[int], list[Any]]:
        """Expand component nodes from stored snapshot node IDs."""
        root_ids = json.loads(root_json)
        if not root_ids:
            return set(), []
        ph = ",".join("?" for _ in root_ids)
        node_rows = self.db.fetchall(
            f"SELECT n.*, f.path as fpath FROM nodes n "
            f"JOIN files f ON n.file_id=f.id WHERE n.id IN ({ph})",
            tuple(root_ids),
        )
        nid_set = {r["id"] for r in node_rows}
        return nid_set, node_rows

    def _build_node_details(self, node_rows: list[Any]) -> list[NodeDetail]:
        """Convert node rows to NodeDetail list."""
        return [
            NodeDetail(
                node_id=r["id"],
                name=r["name"],
                qualified_name=r["qualified_name"],
                node_type=r["node_type"],
                file_path=r["fpath"],
                line_start=r["line_start"],
                line_end=r["line_end"],
                is_deprecated=bool(r["is_deprecated"]),
                type_annotation=r["type_annotation"],
                decorators=json.loads(r["decorators"] or "[]"),
            )
            for r in node_rows
        ]

    def _build_edge_details(self, nid_set: set[int]) -> list[EdgeDetail]:
        """Build edge detail list."""
        nid_list = list(nid_set)
        ph = ",".join("?" for _ in nid_list)
        edge_rows = self.db.fetchall(
            f"""
            SELECT e.*, s.qualified_name as sname, t.qualified_name as tname,
                   f.path as fpath
            FROM edges e JOIN nodes s ON e.source_id=s.id
            JOIN nodes t ON e.target_id=t.id JOIN files f ON e.file_id=f.id
            WHERE e.source_id IN ({ph}) OR e.target_id IN ({ph})
        """,
            tuple(nid_list) + tuple(nid_list),
        )
        return [
            EdgeDetail(
                source_name=r["sname"],
                target_name=r["tname"],
                edge_type=r["edge_type"],
                file_path=r["fpath"],
                line=r["line"],
            )
            for r in edge_rows
        ]

    def _build_warn_details(self, nid_set: set[int]) -> list[WarningDetail]:
        """Build warning detail list."""
        nid_list = list(nid_set)
        ph = ",".join("?" for _ in nid_list)
        warn_rows = self.db.fetchall(
            f"SELECT w.*, f.path as fpath FROM warnings w "
            f"LEFT JOIN files f ON w.file_id=f.id "
            f"WHERE w.node_id IN ({ph}) "
            f"OR ((w.node_id IS NULL OR w.node_id = 0) AND w.file_id IN "
            f"(SELECT file_id FROM nodes WHERE id IN ({ph})))",
            tuple(nid_list) + tuple(nid_list),
        )
        return [
            WarningDetail(
                warn_type=r["warn_type"],
                severity=r["severity"],
                message=r["message"],
                file_path=r["fpath"],
                line=r["line"],
            )
            for r in warn_rows
        ]

    def find_dead_code_tests(self) -> list[TestDeadCodeRef]:
        """Find test files referencing suspected dead code."""
        results = []
        dead_rows = self.db.fetchall(
            "SELECT id, root_node_ids FROM graph_snapshots WHERE is_dead_code=1"
        )
        for dr in dead_rows:
            root_ids = json.loads(dr["root_node_ids"] or "[]")
            if not root_ids:
                continue
            rj = json.dumps(root_ids)
            ref_rows = self.db.fetchall(
                """
                WITH RECURSIVE comp(nid) AS (
                    SELECT value FROM json_each(?)
                    UNION
                    SELECT e.target_id FROM edges e JOIN comp c ON e.source_id=c.nid
                    UNION
                    SELECT e.source_id FROM edges e JOIN comp c ON e.target_id=c.nid
                )
                SELECT DISTINCT e.*, f.path as fpath, f.is_test,
                       n.qualified_name as qname
                FROM edges e
                JOIN comp c ON e.target_id=c.nid
                JOIN nodes n ON e.target_id=n.id
                JOIN files f ON e.file_id=f.id
                WHERE f.is_test=1
            """,
                (rj,),
            )
            for rr in ref_rows:
                results.append(
                    TestDeadCodeRef(
                        test_file=rr["fpath"],
                        line=rr["line"],
                        referenced_symbol=rr["qname"],
                        dead_graph_id=dr["id"],
                    )
                )
        return results

    def validate_hashes(self, graph_id: int) -> bool:
        """Lightweight validation: check mtime for expiry."""
        snap = self.db.fetchone(
            "SELECT root_node_ids FROM graph_snapshots WHERE id=?", (graph_id,)
        )
        if not snap:
            return False
        root_ids = json.loads(snap["root_node_ids"] or "[]")
        if not root_ids:
            return True
        rj = json.dumps(root_ids)
        file_rows = self.db.fetchall(
            """
            SELECT DISTINCT f.path, f.mtime_ns
            FROM files f JOIN nodes n ON f.id=n.file_id
            WHERE n.id IN (SELECT value FROM json_each(?))
        """,
            (rj,),
        )
        for fr in file_rows:
            try:
                st = os.stat(os.path.join(self.root_dir, fr["path"]))
                if st.st_mtime_ns != fr["mtime_ns"]:
                    return False
            except OSError:
                return False
        return True

    def close(self) -> None:
        """Close the database connection."""
        self.db.close()

    @staticmethod
    def _row_to_summary(row: Any) -> GraphSummary:
        """Convert a graph_snapshots row to GraphSummary."""
        entry = row["entry_file"] or ""
        if row["entry_type"]:
            entry += f" ({row['entry_type']})"
        wc = row["warning_count"] or 0
        # Build warning summary string list
        warn_strs = []
        if wc > 0:
            warn_strs.append(f"{wc} warnings")
        return GraphSummary(
            graph_id=row["id"],
            entry=entry,
            entry_file=row["entry_file"] or "",
            entry_line=row["entry_line"],
            node_count=row["node_count"],
            variable_count=row["variable_count"],
            edge_count=row["edge_count"],
            warnings=warn_strs,
            is_dead_code=bool(row["is_dead_code"]),
            is_unreachable=bool(row["is_unreachable"]),
            component_size=row["node_count"] + row["variable_count"],
        )
