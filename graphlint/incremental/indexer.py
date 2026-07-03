# -*- coding: utf-8 -*-
"""Incremental indexer — hash-based incremental/full indexing."""

from __future__ import annotations

import json
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any, Optional

from graphlint.analyzer._types import NodeInfo, ParseResult
from graphlint.analyzer.graph import GraphBuilder
from graphlint.analyzer.parser import _parse_file_worker
from graphlint.analyzer.warnings import WarningCollector, WarningInfo
from graphlint.config.manager import ConfigManager
from graphlint.incremental._db_ops import (
    build_snapshots,
    load_old_changed_node_ids,
    load_prebuilt_edges,
    update_db,
)
from graphlint.storage.db import Database, IndexLock
from graphlint.storage.hashing import compute_file_hash


@dataclass
class IndexResult:
    """Index operation result statistics."""

    files_scanned: int = 0
    files_changed: int = 0
    files_added: int = 0
    files_removed: int = 0
    nodes_added: int = 0
    nodes_removed: int = 0
    edges_updated: int = 0
    duration_ms: int = 0
    warnings_generated: int = 0


class IncrementalIndexer:
    """Incremental index scheduler."""

    def __init__(
        self,
        root_dir: str,
        db: Database,
        parallel_workers: int = 0,
    ) -> None:
        self.root_dir = os.path.realpath(root_dir)
        self.db = db
        self.parallel_workers = (
            parallel_workers if parallel_workers > 0 else (os.cpu_count() or 4)
        )
        self.config_manager = ConfigManager(self.root_dir)
        self.config = self.config_manager.load()

    def run(
        self,
        force_rebuild: bool = False,
        warning_collector: Optional[WarningCollector] = None,
    ) -> IndexResult:
        """Run incremental or full index."""
        start = time.time()
        wc = warning_collector or WarningCollector()
        with IndexLock(self.root_dir):
            result = self._run_inner(force_rebuild, wc)
        result.duration_ms = int((time.time() - start) * 1000)
        return result

    def _run_inner(self, force_rebuild: bool, wc: WarningCollector) -> IndexResult:
        """Internal index logic."""
        if force_rebuild:
            with self.db.transaction():
                for t in (
                    "edges",
                    "nodes",
                    "imports",
                    "warnings",
                    "graph_snapshots",
                    "files",
                ):
                    self.db.execute(f"DELETE FROM {t}")
        disk_files = self._scan()
        db_files_info = {
            r["path"]: (r["hash"], r["mtime_ns"])
            for r in self.db.fetchall("SELECT path, hash, mtime_ns FROM files")
        }
        added, modified, unchanged = [], [], set()
        for fp in disk_files:
            db_info = db_files_info.get(fp)
            abs_p = os.path.join(self.root_dir, fp)
            if db_info is not None and not force_rebuild:
                _, db_mtime = db_info
                disk_stat = os.stat(abs_p)
                if disk_stat.st_mtime_ns == db_mtime:
                    unchanged.add(fp)
                    continue
            cur = compute_file_hash(abs_p)
            if fp not in db_files_info:
                added.append(fp)
            elif cur != db_files_info[fp][0] or force_rebuild:
                modified.append(fp)
            else:
                unchanged.add(fp)
        removed = [fp for fp in db_files_info if fp not in disk_files]
        changed = added + modified
        if not changed and not removed and not force_rebuild:
            return IndexResult(files_scanned=len(disk_files))
        pr_map: dict[str, ParseResult] = {}
        if changed:
            for fp, pr in self._parse_batch(changed):
                pr_map[fp] = pr
                for w in pr.warnings:
                    wc.add(
                        w.warn_type,
                        w.severity,
                        w.message,
                        w.file_path,
                        w.line,
                        w.node_id,
                    )
        if not force_rebuild and unchanged:
            pr_map.update(self._load_unchanged(unchanged))
        builder = self._create_builder(wc)
        incremental = not force_rebuild and bool(changed)

        # 增量模式：加载旧节点 ID 和未变更文件的边
        prebuilt = None
        old_changed_node_ids: dict[int, tuple[str, str]] = {}
        if incremental:
            old_changed_node_ids = load_old_changed_node_ids(self.db, changed)
            if unchanged:
                raw = load_prebuilt_edges(self.db, unchanged)
                if raw:
                    # 构建 SQL fid → memory fid 映射（必须包含所有文件，pr_map 中已含）
                    sql_fid_map = {
                        r["path"]: r["id"]
                        for r in self.db.fetchall("SELECT id, path FROM files")
                    }
                    sql_to_mem = {}
                    for idx, fp in enumerate(pr_map, 1):
                        sfid = sql_fid_map.get(fp)
                        if sfid:
                            sql_to_mem[sfid] = idx
                    for e in raw:
                        mem_fid = sql_to_mem.get(e.file_id)
                        if mem_fid:
                            e.file_id = mem_fid
                    prebuilt = raw

        br = builder.build(
            pr_map,
            changed_files=set(changed) if incremental else None,
            prebuilt_edges=prebuilt,
            old_changed_node_ids=old_changed_node_ids if incremental else None,
        )

        # 重映射预加载边中的旧节点 ID → 新节点 ID（在 build() 内部完成）

        update_db(
            self.db,
            br,
            removed,
            changed,
            self.root_dir,
            self.config.get("test_patterns", {}),
            incremental=incremental,
        )
        if not incremental:
            build_snapshots(self.db, br)
        return IndexResult(
            files_scanned=len(disk_files),
            files_changed=len(modified),
            files_added=len(added),
            files_removed=len(removed),
            nodes_added=len(br.nodes),
            edges_updated=len(br.edges),
            warnings_generated=len(br.warnings),
        )

    # ------------------------------------------------------------------
    # Filesystem scan
    # ------------------------------------------------------------------

    def _scan(self) -> list[str]:
        """Scan all .py files."""
        result = []
        exclude = {
            "__pycache__",
            ".mypy_cache",
            ".pytest_cache",
            ".tox",
            ".venv",
            "venv",
            "env",
            "virtualenv",
            ".env",
            "node_modules",
            ".git",
            ".svn",
            ".hg",
            ".idea",
            ".vscode",
            ".vs",
            ".graphlint",
            "build",
            "dist",
        }
        for dp, dns, fns in os.walk(self.root_dir, topdown=True, followlinks=False):
            dns[:] = [
                d
                for d in dns
                if d not in exclude
                and not d.endswith(".egg-info")
                and not d.startswith(".")
            ]
            for fn in fns:
                if (
                    fn.endswith(".py")
                    and not fn.endswith((".pyc", ".pyo"))
                    and not fn.startswith(".")
                ):
                    result.append(
                        os.path.relpath(
                            os.path.join(dp, fn),
                            self.root_dir,
                        ).replace(os.sep, "/")
                    )
        return result

    # ------------------------------------------------------------------
    # Parallel parsing
    # ------------------------------------------------------------------

    def _parse_batch(self, fps: list[str]) -> list[tuple[str, ParseResult]]:
        """Parse files in parallel using ProcessPoolExecutor."""
        results = []
        workers = min(self.parallel_workers, len(fps), 64) or 1
        with ProcessPoolExecutor(max_workers=workers) as ex:
            futs = {}
            for fp in fps:
                futs[
                    ex.submit(
                        _parse_file_worker,
                        os.path.join(self.root_dir, fp),
                        self.root_dir,
                        self.config,
                    )
                ] = fp
            for fut in as_completed(futs):
                fp = futs[fut]
                try:
                    results.append((fp, fut.result(timeout=30)))
                except Exception:
                    results.append(
                        (
                            fp,
                            ParseResult(
                                file_path=fp,
                                warnings=[
                                    WarningInfo(
                                        warn_type="syntax_error",
                                        severity="error",
                                        message=f"Parse failed: {fp}",
                                        file_path=fp,
                                    )
                                ],
                            ),
                        )
                    )
        return results

    # ------------------------------------------------------------------
    # Load unchanged
    # ------------------------------------------------------------------

    def _load_unchanged(self, unchanged: set[str]) -> dict[str, ParseResult]:
        """Load node data for unchanged files from SQLite."""
        results: dict[str, ParseResult] = {}
        if not unchanged:
            return results
        ph = ",".join("?" for _ in unchanged)
        rows = self.db.fetchall(
            f"SELECT id, path FROM files WHERE path IN ({ph})",
            tuple(unchanged),
        )
        fid_map = {r["id"]: r["path"] for r in rows}
        if not fid_map:
            return results
        fids = list(fid_map)
        fph = ",".join("?" for _ in fids)
        nrows = self.db.fetchall(
            f"SELECT * FROM nodes WHERE file_id IN ({fph})",
            tuple(fids),
        )
        nodes_by_fid: dict[int, list[Any]] = {}
        for row in nrows:
            nodes_by_fid.setdefault(row["file_id"], []).append(_row_to_node(row))
        for fid, fp in fid_map.items():
            results[fp] = ParseResult(
                file_path=fp,
                nodes=nodes_by_fid.get(fid, []),
                imports=[],
                name_usages=set(),
                warnings=[],
                hash="",
            )
        return results

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _create_builder(self, wc: WarningCollector) -> GraphBuilder:
        cfg: dict[str, Any] = dict(self.config)
        cfg["_root_dir"] = self.root_dir
        return GraphBuilder(warning_collector=wc, config=cfg)


def _row_to_node(row: Any) -> NodeInfo:
    """Convert sqlite3.Row to NodeInfo."""

    return NodeInfo(
        id=row["id"],
        file_id=row["file_id"],
        name=row["name"],
        qualified_name=row["qualified_name"],
        node_type=row["node_type"],
        line_start=row["line_start"],
        line_end=row["line_end"],
        col_offset=row["col_offset"],
        parent_node_id=row["parent_node_id"] or 0,
        is_deprecated=bool(row["is_deprecated"]),
        deprecation_msg=row["deprecation_msg"] or "",
        type_annotation=row["type_annotation"] or "",
        is_async=bool(row["is_async"]),
        decorators=json.loads(row["decorators"] or "[]"),
        docstring=row["docstring"] or "",
        is_entry=bool(row["is_entry"]),
    )
