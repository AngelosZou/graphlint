# -*- coding: utf-8 -*-
"""Python API — query / build / configure public interface."""

from __future__ import annotations

import json
import os
import time
from typing import Any, Optional, Union

import sys
import traceback

from graphlint.analyzer.warnings import WarningCollector
from graphlint.config.manager import ConfigManager
from graphlint.exceptions import InvalidParamError, InvalidPathError
from graphlint.i18n import I18nManager
from graphlint.incremental.indexer import IncrementalIndexer
from graphlint.params import VALID_SORT_BY, VALID_WARN_TYPES
from graphlint.query.engine import QueryEngine, QueryFilters
from graphlint.query.formatter import TextFormatter
from graphlint.query.volume import VolumeStrategy
from graphlint.storage.db import Database

# ---------------------------------------------------------------------------
# query
# ---------------------------------------------------------------------------


def query(
    include_tests: bool = False,
    exclude_clean: bool = False,
    exclude_unreachable: bool = False,
    dead_code_tests: bool = False,
    graph_id: Optional[int] = None,
    json_output: bool = False,
    path_format: str = "relative",
    root_dir: str = ".",
    max_results: int = 50,
    min_nodes: int = 0,
    max_nodes: Optional[int] = None,
    warn_types: Optional[str] = None,
    sort_by: str = "warnings",
    detail_level: str = "auto",
    output_limit: int = 8000,
    edge_limit: int = 10,
    file_limit: int = 10,
    node_limit: int = 30,
    no_scan: bool = False,
    lang: str = "system",
) -> Union[str, dict[str, Any]]:
    """Query the dependency graph."""
    # Parameter validation
    root_dir = _validate_root_dir(root_dir)
    _validate_query_params(
        graph_id, min_nodes, max_nodes, max_results, output_limit, path_format, sort_by
    )
    wt_list = _parse_warn_types(warn_types)
    cm = ConfigManager(root_dir)
    config = cm.load()
    i18n = I18nManager(lang if lang != "system" else config.get("lang", "system"))
    formatter = TextFormatter(i18n, path_format, root_dir)

    t0 = time.time()

    # Auto incremental build (filesystem scan only if unchanged)
    if not no_scan:
        if not _auto_build(root_dir, config):
            print(
                "[graphlint] Warning: index may be stale. "
                "Run 'graphlint build --force' to rebuild.",
                file=sys.stderr,
            )

    engine = QueryEngine(os.path.join(root_dir, ".graphlint", "db.sqlite"), root_dir)

    try:
        if graph_id is not None:
            return _query_detail(
                engine,
                graph_id,
                json_output,
                formatter,
                i18n,
                t0,
                no_scan,
                edge_limit,
                file_limit,
                node_limit,
            )

        # List mode
        filters = QueryFilters(
            include_tests=include_tests,
            exclude_clean=exclude_clean,
            exclude_unreachable=exclude_unreachable,
            min_nodes=min_nodes,
            max_nodes=max_nodes,
            warn_types=wt_list,
            sort_by=sort_by,
            max_results=max_results,
            dead_code_tests=dead_code_tests,
        )

        if dead_code_tests:
            return _query_dead_tests(engine, json_output, t0)

        result = engine.list_graphs(filters)
        strategy = VolumeStrategy()
        plan = strategy.decide(
            result.graphs,
            json_output,
            output_limit,
            detail_level,
        )
        elapsed = int((time.time() - t0) * 1000)
        if json_output:
            return formatter.format_json(result, root_dir, elapsed)
        return formatter.format_query_result(result, plan)

    finally:
        engine.close()


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------


def build(
    force_rebuild: bool = False,
    parallel: int = 0,
    root_dir: str = ".",
    lang: str = "system",
) -> dict[str, Any]:
    """Build/update the index."""
    root_dir = _validate_root_dir(root_dir)
    if parallel < 0:
        raise InvalidParamError("parallel", str(parallel), "must be >= 0")
    if parallel > 64:
        parallel = 64

    _ = ConfigManager(root_dir).load()
    db = Database(root_dir)
    wc = WarningCollector()

    try:
        indexer = IncrementalIndexer(root_dir, db, parallel)
        result = indexer.run(force_rebuild=force_rebuild, warning_collector=wc)
        return {
            "status": "ok",
            "files_scanned": result.files_scanned,
            "files_changed": result.files_changed,
            "files_added": result.files_added,
            "files_removed": result.files_removed,
            "nodes_added": result.nodes_added,
            "edges_updated": result.edges_updated,
            "duration_ms": result.duration_ms,
            "warnings_generated": result.warnings_generated,
        }
    finally:
        db.close()


# ---------------------------------------------------------------------------
# configure
# ---------------------------------------------------------------------------


def configure(
    action: str,
    key: Optional[str] = None,
    value: Optional[str] = None,
    source: Optional[str] = None,
    root_dir: str = ".",
    lang: Optional[str] = None,
    rule_json: Optional[str] = None,
    rule_name: Optional[str] = None,
    exclude_pattern: Optional[str] = None,
) -> dict[str, Any]:
    """Manage configuration."""
    root_dir = _validate_root_dir(root_dir)
    valid_actions = {
        "show",
        "set",
        "get",
        "copy-from",
        "add-entry-rule",
        "remove-entry-rule",
        "add-exclude",
        "remove-exclude",
    }
    if action not in valid_actions:
        return {"status": "error", "message": f"Invalid action: {action}"}

    try:
        cm = ConfigManager(root_dir)
        # Apply lang override if explicitly provided
        if lang is not None and lang != "system":
            cm.set("lang", lang)
        if action == "show":
            return {"status": "ok", "config": cm.show()}
        if action == "get":
            if not key:
                return {"status": "error", "message": "--key required"}
            return {"status": "ok", "key": key, "value": cm.get(key)}
        if action == "set":
            if not key or value is None:
                return {"status": "error", "message": "--key and --value required"}
            cm.set(key, _coerce_value(value))
            return {"status": "ok", "message": f"Set {key}={value}"}
        if action == "copy-from":
            if not source:
                return {"status": "error", "message": "--from required"}
            cm.copy_from(source)
            return {"status": "ok", "message": f"Config copied from {source}"}
        if action == "add-entry-rule":
            return _cfg_add_rule(cm, rule_json)
        if action == "remove-entry-rule":
            return _cfg_remove_rule(cm, rule_name)
        if action == "add-exclude":
            return _cfg_add_exclude(cm, exclude_pattern)
        if action == "remove-exclude":
            return _cfg_remove_exclude(cm, exclude_pattern)
        return {"status": "error", "message": f"Unknown action: {action}"}
    except Exception as exc:
        return {"status": "error", "message": str(exc)}


def _validate_query_params(
    graph_id: Optional[int],
    min_nodes: int,
    max_nodes: Optional[int],
    max_results: int,
    output_limit: int,
    path_format: str,
    sort_by: str,
) -> None:
    """Validate query parameters."""
    if graph_id is not None and graph_id <= 0:
        raise InvalidParamError("graph_id", str(graph_id), "must be > 0")
    if min_nodes < 0:
        raise InvalidParamError("min_nodes", str(min_nodes), "must be >= 0")
    if max_nodes is not None and max_nodes < 1:
        raise InvalidParamError("max_nodes", str(max_nodes), "must be >= 1")
    if max_results < 1 or max_results > 1000:
        raise InvalidParamError("max_results", str(max_results), "1-1000")
    if output_limit < 100 or output_limit > 100000:
        raise InvalidParamError("output_limit", str(output_limit), "100-100000")
    if path_format not in ("absolute", "relative"):
        raise InvalidParamError("path_format", path_format)
    if sort_by not in VALID_SORT_BY:
        raise InvalidParamError("sort_by", sort_by)


def _validate_root_dir(root_dir: str) -> str:
    """Validate and normalize the root directory path."""
    real = os.path.realpath(root_dir)
    if not os.path.isdir(real):
        raise InvalidPathError(root_dir, "directory does not exist")
    return real


def _parse_warn_types(warn_types: Optional[str]) -> Optional[list[str]]:
    """Parse warn_types string into a list and validate."""
    if not warn_types:
        return None
    items = [w.strip() for w in warn_types.split(",") if w.strip()]
    for w in items:
        if w not in VALID_WARN_TYPES:
            raise InvalidParamError(
                "warn_types",
                w,
                f"Invalid warn type. Allowed: {sorted(VALID_WARN_TYPES)}",
            )
    return items


def _scan_current(root_dir: str) -> tuple[bool, dict[str, int]]:
    """Scan .py files and detect changes against the last saved stamp.

    Returns (changed, current_files) where current_files maps
    each .py file's relative path to its mtime_ns.
    """
    stamp_file = os.path.join(root_dir, ".graphlint", ".last_scan_stamp")
    stamp_ok = True
    try:
        with open(stamp_file, "r") as f:
            saved = json.loads(f.read())
    except (FileNotFoundError, json.JSONDecodeError):
        saved = {}
        stamp_ok = False
    saved_files = saved.get("files", {})

    exclude = {
        "__pycache__", ".mypy_cache", ".pytest_cache", ".tox",
        ".venv", "venv", "env", "virtualenv", ".env",
        "node_modules", ".git", ".svn", ".hg", ".idea",
        ".vscode", ".vs", ".graphlint", "build", "dist",
    }
    current_files = {}
    changed = False
    for dp, dns, fns in os.walk(root_dir, topdown=True, followlinks=False):
        dns[:] = [d for d in dns if d not in exclude
                  and not d.endswith(".egg-info") and not d.startswith(".")]
        for fn in fns:
            if fn.endswith(".py") and not fn.endswith((".pyc", ".pyo")) and not fn.startswith("."):
                rel = os.path.relpath(os.path.join(dp, fn), root_dir).replace(os.sep, "/")
                try:
                    mtime = os.stat(os.path.join(dp, fn)).st_mtime_ns
                except OSError:
                    changed = True
                    continue
                current_files[rel] = mtime
                saved_mtime = saved_files.get(rel)
                if saved_mtime is None or saved_mtime != mtime:
                    changed = True

    # Detect file deletions
    for path in saved_files:
        if path not in current_files:
            changed = True
            break

    if not stamp_ok:
        changed = True

    return changed, current_files


def _auto_build(root_dir: str, config: dict[str, Any]) -> bool:
    """Run auto build. Returns True on success. Builds from scratch if files changed."""
    changed, current_files = _scan_current(root_dir)
    if not changed:
        return True
    db = None
    try:
        db = Database(root_dir)
        wc = WarningCollector()
        parallel = config.get("performance", {}).get("parallel_workers", 0)
        indexer = IncrementalIndexer(root_dir, db, parallel)
        indexer.run(force_rebuild=False, warning_collector=wc, pre_scanned_files=current_files)
        return True
    except Exception as exc:
        msg = str(exc)
        is_fk = "FOREIGN KEY constraint failed" in msg
        if is_fk:
            traceback.print_exc(file=sys.stderr)
        print(f"[graphlint] Auto build failed: {msg}", file=sys.stderr)
        if is_fk:
            print("[graphlint] FK constraint — retrying with full rebuild...", file=sys.stderr)
            try:
                if db is not None:
                    try:
                        db.close()
                    except Exception:
                        pass
                db2 = Database(root_dir)
                wc2 = WarningCollector()
                indexer2 = IncrementalIndexer(root_dir, db2, parallel)
                indexer2.run(force_rebuild=True, warning_collector=wc2)
                return True
            except Exception as exc2:
                print(f"[graphlint] Full rebuild also failed: {exc2}", file=sys.stderr)
                traceback.print_exc(file=sys.stderr)
                return False
            finally:
                if db2 is not None:
                    try:
                        db2.close()
                    except Exception:
                        pass
        return False
    finally:
        if db is not None:
            try:
                db.close()
            except Exception:
                pass


def _coerce_value(value: str) -> Any:
    """Try to coerce a string value to an appropriate type."""
    if value.lower() in ("true", "yes"):
        return True
    if value.lower() in ("false", "no"):
        return False
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------


def _query_detail(
    engine: QueryEngine,
    graph_id: int,
    json_output: bool,
    formatter: TextFormatter,
    i18n: I18nManager,
    t0: float,
    no_scan: bool,
    edge_limit: int = 10,
    file_limit: int = 10,
    node_limit: int = 30,
) -> Union[str, dict[str, Any]]:
    """Handle graph_id detail query."""
    if no_scan and not engine.validate_hashes(graph_id):
        elapsed = int((time.time() - t0) * 1000)
        if json_output:
            return {
                "status": "error",
                "message": i18n.t("error.hash_mismatch"),
                "query_time_ms": elapsed,
            }
        return i18n.t("error.hash_mismatch")
    detail = engine.get_graph_detail(graph_id)
    if detail is None:
        elapsed = int((time.time() - t0) * 1000)
        msg = i18n.t("error.invalid_graph_id", id=graph_id, max="?")
        return (
            {"status": "error", "message": msg, "query_time_ms": elapsed}
            if json_output
            else msg
        )
    elapsed = int((time.time() - t0) * 1000)
    if json_output:
        return formatter.format_json_detail(
            detail, elapsed, edge_limit, file_limit, node_limit
        )
    return formatter.format_graph_detail(detail, edge_limit, file_limit, node_limit)


def _query_dead_tests(
    engine: QueryEngine, json_output: bool, t0: float
) -> Union[str, dict[str, Any]]:
    """Handle dead code test query."""
    refs = engine.find_dead_code_tests()
    elapsed = int((time.time() - t0) * 1000)
    if json_output:
        return {
            "status": "ok",
            "query_time_ms": elapsed,
            "dead_code_tests": [
                {
                    "test_file": r.test_file,
                    "line": r.line,
                    "referenced_symbol": r.referenced_symbol,
                    "dead_graph_id": r.dead_graph_id,
                }
                for r in refs
            ],
        }
    lines = [f"Dead code test references ({len(refs)}):"]
    for r in refs:
        lines.append(
            f"  {r.test_file}:{r.line} → {r.referenced_symbol} "
            f"(dead code graph #{r.dead_graph_id})"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------


def _cfg_add_rule(cm: ConfigManager, rule_json: Optional[str]) -> dict[str, Any]:
    if not rule_json:
        return {"status": "error", "message": "--rule-json required"}
    rule = json.loads(rule_json)
    cm.add_entry_rule(rule)
    return {"status": "ok", "message": "Entry rule added"}


def _cfg_remove_rule(cm: ConfigManager, rule_name: Optional[str]) -> dict[str, Any]:
    if not rule_name:
        return {"status": "error", "message": "--name required"}
    cm.remove_entry_rule(rule_name)
    return {"status": "ok", "message": f"Entry rule '{rule_name}' removed"}


def _cfg_add_exclude(
    cm: ConfigManager, exclude_pattern: Optional[str]
) -> dict[str, Any]:
    if not exclude_pattern:
        return {"status": "error", "message": "--exclude-pattern required"}
    cm.add_exclude_pattern(exclude_pattern)
    return {"status": "ok", "message": f"Exclude pattern '{exclude_pattern}' added"}


def _cfg_remove_exclude(
    cm: ConfigManager, exclude_pattern: Optional[str]
) -> dict[str, Any]:
    if not exclude_pattern:
        return {"status": "error", "message": "--exclude-pattern required"}
    cm.remove_exclude_pattern(exclude_pattern)
    return {"status": "ok", "message": f"Exclude pattern '{exclude_pattern}' removed"}
