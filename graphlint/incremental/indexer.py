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
from graphlint.analyzer.language.python.parser import _parse_file_worker
from graphlint.analyzer.language.registry import LanguageRegistry
from graphlint.analyzer.warnings import WarningCollector, WarningInfo
from graphlint.config.manager import ConfigManager
from graphlint.incremental._db_ops import (
    build_snapshots,
    load_old_changed_node_ids,
    load_prebuilt_edges,
    update_db,
    update_snapshots,
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
        registry: Optional[LanguageRegistry] = None,
    ) -> None:
        self.root_dir = os.path.realpath(root_dir)
        self.db = db
        self.parallel_workers = (
            parallel_workers if parallel_workers > 0 else (os.cpu_count() or 4)
        )
        self.config_manager = ConfigManager(self.root_dir)
        self.config = self.config_manager.load()
        self.registry = registry

    def run(
        self,
        force_rebuild: bool = False,
        warning_collector: Optional[WarningCollector] = None,
        pre_scanned_files: Optional[dict[str, int]] = None,
    ) -> IndexResult:
        """Run incremental or full index.

        pre_scanned_files skips the internal filesystem scan.
        """
        start = time.time()
        wc = warning_collector or WarningCollector()
        with IndexLock(self.root_dir):
            result = self._run_inner(force_rebuild, wc, pre_scanned_files)
        result.duration_ms = int((time.time() - start) * 1000)
        return result

    def _run_inner(
        self,
        force_rebuild: bool,
        wc: WarningCollector,
        pre_scanned_files: Optional[dict[str, int]] = None,
    ) -> IndexResult:
        """Index files — incremental rebuild on changes, full rebuild on force."""
        if pre_scanned_files is not None:
            disk_files = list(pre_scanned_files.keys())
            file_mtimes = pre_scanned_files
        else:
            scanned = self._scan_with_mtime()
            file_mtimes = {}
            disk_files = []
            for rel, mtime in scanned:
                file_mtimes[rel] = mtime
                disk_files.append(rel)

        db_files_info = {
            r["path"]: (r["hash"], r["mtime_ns"])
            for r in self.db.fetchall("SELECT path, hash, mtime_ns FROM files")
        }
        needs_full = force_rebuild or not db_files_info
        hash_cache: dict[str, str] = {}
        added, modified, unchanged = [], [], set()
        for fp in disk_files:
            db_info = db_files_info.get(fp)
            abs_p = os.path.join(self.root_dir, fp)
            if db_info is not None and not force_rebuild:
                _, db_mtime = db_info
                disk_mtime = file_mtimes.get(fp)
                if disk_mtime == db_mtime:
                    unchanged.add(fp)
                    continue
            if needs_full:
                if fp not in db_files_info:
                    added.append(fp)
                else:
                    modified.append(fp)
                continue
            cur = compute_file_hash(abs_p)
            hash_cache[fp] = cur
            if fp not in db_files_info:
                added.append(fp)
            elif cur != db_files_info[fp][0]:
                modified.append(fp)
            else:
                unchanged.add(fp)
        removed = [fp for fp in db_files_info if fp not in disk_files]
        changed = added + modified

        if not changed and not removed and not needs_full:
            self._update_scan_stamp(disk_files, file_mtimes)
            return IndexResult(files_scanned=len(disk_files))

        pr_map: dict[str, ParseResult] = {}

        if needs_full:
            with self.db.transaction():
                for t in ("edges", "nodes", "imports", "warnings", "graph_snapshots", "files"):
                    self.db.execute(f"DELETE FROM {t}")
            all_results = self._parse_batch(disk_files)
            for fp, pr in all_results:
                pr_map[fp] = pr
                for w in pr.warnings:
                    wc.add(w.warn_type, w.severity, w.message, w.file_path, w.line, w.node_id)
            builder = self._create_builder(wc)
            br = builder.build(pr_map)
            update_db(
                self.db, br, [], list(pr_map),
                self.root_dir, self.config.get("test_patterns", {}),
                incremental=False,
            )
            build_snapshots(self.db, br)
        else:
            if changed:
                for fp, pr in self._parse_batch(changed):
                    if fp in hash_cache:
                        pr.hash = hash_cache[fp]
                    pr_map[fp] = pr
                    for w in pr.warnings:
                        wc.add(w.warn_type, w.severity, w.message, w.file_path, w.line, w.node_id)
            if unchanged:
                pr_map.update(self._load_unchanged(unchanged))

            old_ids: dict[int, tuple[str, str]] = {}
            prebuilt = None
            if changed:
                old_ids = load_old_changed_node_ids(self.db, changed)
                if unchanged:
                    sql_fid_map = {
                        r["path"]: r["id"]
                        for r in self.db.fetchall("SELECT id, path FROM files")
                    }
                    sql_to_mem = {}
                    for idx, fp in enumerate(pr_map, 1):
                        sfid = sql_fid_map.get(fp)
                        if sfid:
                            sql_to_mem[sfid] = idx
                    prebuilt = load_prebuilt_edges(self.db, unchanged, sql_to_mem)

            builder = self._create_builder(wc)
            br = builder.build(
                pr_map,
                changed_files=set(changed) if changed else None,
                prebuilt_edges=prebuilt,
                old_changed_node_ids=old_ids if old_ids else None,
            )
            update_db(
                self.db, br, removed, changed,
                self.root_dir, self.config.get("test_patterns", {}),
                incremental=True,
            )
            update_snapshots(self.db, br)

        self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self._update_scan_stamp(disk_files, file_mtimes)
        return IndexResult(
            files_scanned=len(disk_files),
            files_changed=len(modified),
            files_added=len(added),
            files_removed=len(removed),
            nodes_added=len(br.nodes),
            edges_updated=len(br.edges),
            warnings_generated=len(br.warnings),
        )

    def _update_scan_stamp(self, disk_files=None, current_mtimes=None):
        """Save current file snapshot for fast change detection on next run."""
        if disk_files is None:
            scanned = self._scan_with_mtime()
            disk_files = [rel for rel, _ in scanned]
            current_mtimes = dict(scanned)

        files = {}
        if current_mtimes is not None:
            for rel in disk_files:
                if rel in current_mtimes:
                    files[rel] = current_mtimes[rel]
        else:
            for rel in disk_files:
                abs_p = os.path.join(self.root_dir, rel)
                try:
                    files[rel] = os.stat(abs_p).st_mtime_ns
                except OSError:
                    pass

        stamp_path = os.path.join(self.root_dir, ".graphlint", ".last_scan_stamp")
        os.makedirs(os.path.dirname(stamp_path), exist_ok=True)
        with open(stamp_path, "w") as f:
            json.dump({"files": files}, f)

    def _scan_with_mtime(self) -> list[tuple[str, int]]:
        """Scan source files via the language registry."""
        if self.registry:
            return self.registry.scan_files(self.root_dir)
        return []

    # -- Parallel parsing -------------------------------------------------

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

    # -- Load unchanged from DB ----------------------------------------

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
        return GraphBuilder(warning_collector=wc, config=cfg, registry=self.registry)


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
