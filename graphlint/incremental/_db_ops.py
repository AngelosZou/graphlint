# -*- coding: utf-8 -*-
"""Indexer database operation helper functions."""

from __future__ import annotations

import datetime
import hashlib
import json
import os
from typing import Any, Optional

from graphlint.analyzer._types import EdgeInfo, NodeInfo, GraphBuildResult
from graphlint.storage.db import Database
from graphlint.storage.hashing import compute_file_hash, is_test_file

_UTC = datetime.timezone.utc


def _is_test_entry(e: Any) -> bool:
    """Check whether *e* (an EntryInfo) points to a test file."""
    fp = getattr(e, "file_path", "") or ""
    basename = os.path.basename(fp)
    return (
        basename.startswith("test_")
        or basename.endswith("_test.py")
        or basename == "conftest.py"
        or "tests/" in fp.replace(os.sep, "/")
    )


def load_prebuilt_edges(
    db: Database,
    unchanged_files: set[str],
    sql_to_mem: Optional[dict[int, int]] = None,
) -> list[EdgeInfo]:
    """Load edges for unchanged files from DB (incremental build).

    Args:
        sql_to_mem: Optional mapping from SQL file_id to memory file_id.
                    When provided, EdgeInfo file_id values are mapped to memory fid.
    """
    if not unchanged_files:
        return []
    ph = ",".join("?" for _ in unchanged_files)
    rows = db.fetchall(
        f"SELECT e.* FROM edges e JOIN files f ON e.file_id=f.id WHERE f.path IN ({ph})",
        tuple(unchanged_files),
    )
    result = []
    for r in rows:
        sql_fid = r["file_id"]
        mem_fid = sql_to_mem.get(sql_fid) if sql_to_mem else sql_fid
        if not mem_fid:
            continue
        result.append(EdgeInfo(
            source_id=r["source_id"],
            target_id=r["target_id"],
            edge_type=r["edge_type"],
            file_id=mem_fid,
            line=r["line"],
            context=r["context"] or "",
        ))
    return result


def load_old_changed_node_ids(
    db: Database,
    changed_files: list[str],
) -> dict[int, tuple[str, str]]:
    """Load old node IDs for changed files from DB for edge remapping."""
    if not changed_files:
        return {}
    ph = ",".join("?" for _ in changed_files)
    rows = db.fetchall(
        f"SELECT n.id, n.qualified_name, f.path FROM nodes n "
        f"JOIN files f ON n.file_id=f.id WHERE f.path IN ({ph})",
        tuple(changed_files),
    )
    return {r["id"]: (r["qualified_name"], r["path"]) for r in rows}


def update_db(
    db: Database,
    build_result: GraphBuildResult,
    removed: list[str],
    changed: list[str],
    root_dir: str,
    test_patterns: dict[str, Any],
    incremental: bool = False,
) -> None:
    """Update SQLite in a single transaction."""
    changed_set = set(changed) if incremental else None
    with db.transaction():
        if incremental:
            _delete_old(db, removed, changed)
        else:
            # Full build: unconditionally clear all data tables (keep files table)
            # files table is updated by subsequent _upsert_files INSERT OR REPLACE
            for tbl in ("edges", "nodes", "imports", "warnings", "graph_snapshots"):
                db.execute(f"DELETE FROM {tbl}")
        _upsert_files(db, build_result, root_dir, test_patterns, changed)
        fid_map = _load_fid_map(db)
        _insert_nodes(db, build_result, fid_map, changed_files=changed_set)
        _do_insert_edges(db, build_result, fid_map, changed_files=changed_set)
        _insert_warnings(db, build_result, fid_map, changed_files=changed_set)
        if incremental:
            update_snapshots(db, build_result)
        else:
            db.execute("DELETE FROM graph_snapshots")


def _delete_old(db: Database, removed: list[str], changed: list[str]) -> None:
    """Delete old data for removed/changed files."""
    for paths in (removed, changed):
        if not paths:
            continue
        ph = ",".join("?" for _ in paths)
        for tbl in ("edges", "nodes", "imports", "warnings"):
            db.execute(
                f"DELETE FROM {tbl} WHERE file_id IN "
                f"(SELECT id FROM files WHERE path IN ({ph}))",
                tuple(paths),
            )
    if removed:
        ph = ",".join("?" for _ in removed)
        db.execute(f"DELETE FROM files WHERE path IN ({ph})", tuple(removed))


def _upsert_files(
    db: Database,
    build_result: GraphBuildResult,
    root_dir: str,
    test_patterns: dict[str, Any],
    changed_files: Optional[list[str]] = None,
) -> None:
    """Insert or update the files table for changed files only."""
    if changed_files is None:
        changed_files = build_result.files
    now = datetime.datetime.now(_UTC).isoformat()
    for fp in build_result.files:
        if fp not in changed_files:
            continue
        pr = build_result.files_data.get(fp)
        if not pr:
            continue
        abs_p = os.path.join(root_dir, fp)
        try:
            st = os.stat(abs_p)
            size, mtime = st.st_size, st.st_mtime_ns
        except OSError:
            size, mtime = 0, 0
        is_test = 1 if is_test_file(fp, test_patterns) else 0
        fhash = pr.hash or compute_file_hash(abs_p)
        db.execute(
            "INSERT OR REPLACE INTO files "
            "(path, hash, size_bytes, mtime_ns, is_test, "
            "parse_status, last_parsed_at) VALUES (?,?,?,?,?,?,?)",
            (fp, fhash, size, mtime, is_test, "parsed", now),
        )


def _load_fid_map(db: Database) -> dict[str, int]:
    """Load the file_id mapping."""
    result: dict[str, int] = {}
    for row in db.fetchall("SELECT id, path FROM files"):
        result[row["path"]] = row["id"]
    return result


def _insert_nodes(
    db: Database,
    build_result: GraphBuildResult,
    fid_map: dict[str, int],
    changed_files: Optional[set[str]] = None,
) -> None:
    """Insert nodes sorted by parent dependency for FK-safe ordering."""
    # build_result.files[fid-1] = path for each memory file_id
    mem_fid_to_path: dict[int, str] = dict(enumerate(build_result.files, 1))

    rows: list[tuple[Any, ...]] = []
    for node in build_result.nodes:
        if node.id == 0:
            continue
        fp = mem_fid_to_path.get(node.file_id, "")
        if changed_files is not None and fp not in changed_files:
            continue
        fid = fid_map.get(fp, 0)
        node_id = node.id or 0
        if not fid or node_id == 0:
            continue
        rows.append(
            (
                node_id, fid, node.name, node.qualified_name, node.node_type,
                node.line_start, node.line_end, node.col_offset,
                node.parent_node_id or None,
                1 if node.is_deprecated else 0,
                node.deprecation_msg or None,
                node.type_annotation or None,
                1 if node.is_async else 0,
                json.dumps(node.decorators or []),
                node.docstring or None,
                1 if node.is_entry else 0,
            )
        )

    # parents before children to avoid FK violations on parent_node_id
    rows.sort(key=lambda r: (0 if r[8] is None else 1, r[8] or 0, r[0]))

    for i in range(0, len(rows), 5000):
        batch = rows[i:i + 5000]
        db.executemany(
            "INSERT OR REPLACE INTO nodes (id, file_id, name, qualified_name, node_type, "
            "line_start, line_end, col_offset, parent_node_id, "
            "is_deprecated, deprecation_msg, type_annotation, is_async, "
            "decorators, docstring, is_entry) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            batch,
        )


def _do_insert_edges(
    db: Database,
    build_result: GraphBuildResult,
    fid_map: dict[str, int],
    changed_files: Optional[set[str]] = None,
) -> None:
    """Insert edges, skipping dangling ones with source_id=0 or target_id=0."""
    mem_fid_to_sql: dict[int, int] = {}
    for idx, fp in enumerate(build_result.files, 1):
        sql_fid = fid_map.get(fp, 0)
        if sql_fid:
            mem_fid_to_sql[idx] = sql_fid

    if changed_files is not None:
        # Delete all edges globally and re-insert to keep data consistent.
        db.execute("DELETE FROM edges")

    batch: list[tuple[Any, ...]] = []
    for edge in build_result.edges:
        if edge.source_id == 0 or edge.target_id == 0:
            continue
        sql_fid = mem_fid_to_sql.get(edge.file_id, 0)
        if not sql_fid:
            continue
        batch.append(
            (
                edge.source_id,
                edge.target_id,
                edge.edge_type,
                sql_fid,
                edge.line,
                edge.context or None,
            )
        )
        if len(batch) >= 5000:
            db.executemany(
                "INSERT INTO edges (source_id, target_id, edge_type, "
                "file_id, line, context) VALUES (?,?,?,?,?,?)",
                batch,
            )
            batch.clear()
    if batch:
        db.executemany(
            "INSERT INTO edges (source_id, target_id, edge_type, "
            "file_id, line, context) VALUES (?,?,?,?,?,?)",
            batch,
        )


def _insert_warnings(
    db: Database,
    build_result: GraphBuildResult,
    fid_map: dict[str, int],
    changed_files: Optional[set[str]] = None,
) -> None:
    """Insert warnings."""
    batch: list[tuple[Any, ...]] = []
    for w in build_result.warnings:
        if (
            changed_files is not None
            and w.file_path
            and w.file_path not in changed_files
        ):
            continue
        wfid = fid_map.get(w.file_path or "")
        batch.append(
            (
                wfid,
                w.node_id or None,
                w.warn_type,
                w.severity,
                w.message,
                w.line or 0,
                json.dumps(w.details or {}),
            )
        )
    if batch:
        db.executemany(
            "INSERT INTO warnings (file_id, node_id, warn_type, "
            "severity, message, line, details) VALUES (?,?,?,?,?,?,?)",
            batch,
        )


def _precompute_edge_counts(
    component_map: dict[int, int],
    edges: list[EdgeInfo],
) -> dict[int, int]:
    """Pre-compute edge counts per component with a single pass over all edges.

    Returns:
        Mapping of comp_id -> edge_count
    """
    counts: dict[int, int] = {}
    for e in edges:
        cs = component_map.get(e.source_id)
        ct = component_map.get(e.target_id)
        if cs is not None:
            counts[cs] = counts.get(cs, 0) + 1
        if ct is not None and ct != cs:
            counts[ct] = counts.get(ct, 0) + 1
    return counts


def _component_stats(
    comp: Any,
    build_result: GraphBuildResult,
    nid_map: dict[int, Any],
    edge_counts: dict[int, int],
) -> tuple[Any, ...]:
    """Compute component statistics."""
    cf_count = sum(
        1
        for nid in comp.node_ids
        if nid_map.get(nid, NodeInfo()).node_type in ("class", "function", "method")
    )
    var_count = sum(
        1
        for nid in comp.node_ids
        if nid_map.get(nid, NodeInfo()).node_type in ("variable", "field")
    )
    ec = edge_counts.get(comp.component_id, 0)
    wc = sum(1 for w in build_result.warnings if w.node_id in comp.node_ids)
    root_ids = sorted(nid for nid in comp.node_ids if nid != 0)
    root_json = json.dumps(root_ids)
    comp_hash = hashlib.sha256(root_json.encode()).hexdigest()
    return cf_count, var_count, ec, wc, root_json, comp_hash


def _snapshot_values(
    comp: Any,
    now: str,
    cf_count: int,
    var_count: int,
    ec: int,
    wc: int,
    root_json: str,
    comp_hash: str,
) -> tuple[Any, ...]:
    """Return snapshot VALUES tuple."""
    entry_file, entry_line, entry_type = None, None, ""
    if comp.entry_info:
        # Prefer entries with non-test entry_file so the main component
        # is visible when include_tests=False.
        non_test = [e for e in comp.entry_info if not _is_test_entry(e)]
        best = non_test[0] if non_test else comp.entry_info[0]
        entry_file = best.file_path
        entry_line = best.line
        entry_type = best.rule_name
    return (
        now,
        entry_file,
        entry_line,
        entry_type,
        cf_count,
        var_count,
        ec,
        wc,
        1 if comp.is_dead_code else 0,
        1 if comp.is_unreachable else 0,
        root_json,
        comp_hash,
    )


def _save_component_members(
    db: Database,
    component_map: dict[int, int],
) -> None:
    """Write component_members mapping for incremental connectivity analysis."""
    db.execute("DELETE FROM component_members")

    batch: list[tuple[int, int]] = []
    for nid, cid in component_map.items():
        if nid == 0:
            continue
        batch.append((cid, nid))
        if len(batch) >= 5000:
            db.executemany(
                "INSERT INTO component_members (component_id, node_id) VALUES (?,?)",
                batch,
            )
            batch.clear()
    if batch:
        db.executemany(
            "INSERT INTO component_members (component_id, node_id) VALUES (?,?)",
            batch,
        )


def build_snapshots(
    db: Database,
    build_result: GraphBuildResult,
) -> None:
    """Create graph_snapshot records for each component (full mode, auto ID)."""
    now = datetime.datetime.now(_UTC).isoformat()
    nid_map = (
        build_result.node_id_map
        if hasattr(build_result, "node_id_map")
        else getattr(build_result, "_node_id_map", {})
    )
    # Pre-compute edge counts for all components (single pass, avoids per-component full traversal)
    edge_counts = _precompute_edge_counts(
        build_result.component_map,
        build_result.edges,
    )
    for comp in build_result.components:
        stats = _component_stats(comp, build_result, nid_map, edge_counts)
        vals = _snapshot_values(comp, now, *stats)
        db.execute(
            "INSERT INTO graph_snapshots "
            "(snapshot_time, entry_file, entry_line, entry_type, "
            "node_count, variable_count, edge_count, warning_count, "
            "is_dead_code, is_unreachable, root_node_ids, component_hash) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            vals,
        )
    _save_component_members(db, build_result.component_map)


def update_snapshots(
    db: Database,
    build_result: GraphBuildResult,
) -> None:
    """Update snapshots incrementally — reuse old IDs by entry_file match."""
    now = datetime.datetime.now(_UTC).isoformat()
    old_map: dict[str, int] = {}
    for row in db.fetchall("SELECT id, entry_file FROM graph_snapshots"):
        ef = row["entry_file"] or ""
        if ef:
            old_map[ef] = row["id"]

    max_id = max(old_map.values()) if old_map else 0
    # Delete old snapshots, re-insert with matched IDs
    db.execute("DELETE FROM graph_snapshots")
    nid_map = (
        build_result.node_id_map
        if hasattr(build_result, "node_id_map")
        else getattr(build_result, "_node_id_map", {})
    )
    # Pre-compute edge counts for all components (single pass, avoids per-component full traversal)
    edge_counts = _precompute_edge_counts(
        build_result.component_map,
        build_result.edges,
    )
    _used_ids: set[int] = set()
    for comp in build_result.components:
        entry_file = comp.entry_info[0].file_path if comp.entry_info else None
        entry_key = entry_file or ""
        snap_id = old_map.get(entry_key)
        if not snap_id:
            max_id += 1
            snap_id = max_id
        # Ensure no ID collision for dead code components (no entry_file)
        while snap_id in _used_ids:
            max_id += 1
            snap_id = max_id
        _used_ids.add(snap_id)
        stats = _component_stats(comp, build_result, nid_map, edge_counts)
        vals = _snapshot_values(comp, now, *stats)
        db.execute(
            "INSERT INTO graph_snapshots "
            "(id, snapshot_time, entry_file, entry_line, entry_type, "
            "node_count, variable_count, edge_count, warning_count, "
            "is_dead_code, is_unreachable, root_node_ids, component_hash) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (snap_id,) + vals,
        )
    _save_component_members(db, build_result.component_map)



