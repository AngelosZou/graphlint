# -*- coding: utf-8 -*-
"""SQLite database schema definition (DDL)."""

from __future__ import annotations

import sqlite3

# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

CREATE_TABLES_SQL: str = """
-- File records
CREATE TABLE IF NOT EXISTS files (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    path            TEXT NOT NULL UNIQUE,
    hash            TEXT NOT NULL,
    size_bytes      INTEGER NOT NULL,
    mtime_ns        INTEGER NOT NULL,
    is_test         INTEGER NOT NULL DEFAULT 0,
    parse_status    TEXT NOT NULL DEFAULT 'pending',
    parse_error     TEXT,
    last_parsed_at  TEXT
);

CREATE INDEX IF NOT EXISTS idx_files_hash ON files(hash);
CREATE INDEX IF NOT EXISTS idx_files_status ON files(parse_status);

-- Nodes
CREATE TABLE IF NOT EXISTS nodes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id         INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    qualified_name  TEXT NOT NULL,
    node_type       TEXT NOT NULL,
    line_start      INTEGER NOT NULL,
    line_end        INTEGER NOT NULL,
    col_offset      INTEGER NOT NULL,
    parent_node_id  INTEGER REFERENCES nodes(id) ON DELETE SET NULL,
    is_deprecated   INTEGER NOT NULL DEFAULT 0,
    deprecation_msg TEXT,
    type_annotation TEXT,
    is_async        INTEGER NOT NULL DEFAULT 0,
    decorators      TEXT,
    docstring       TEXT,
    is_entry        INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_nodes_file ON nodes(file_id);
CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(node_type);
CREATE INDEX IF NOT EXISTS idx_nodes_qualified ON nodes(qualified_name);
CREATE INDEX IF NOT EXISTS idx_nodes_deprecated ON nodes(is_deprecated)
    WHERE is_deprecated = 1;

-- Edges
CREATE TABLE IF NOT EXISTS edges (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id       INTEGER NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    target_id       INTEGER NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    edge_type       TEXT NOT NULL,
    file_id         INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    line            INTEGER NOT NULL,
    context         TEXT
);

CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);
CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id);
CREATE INDEX IF NOT EXISTS idx_edges_type ON edges(edge_type);
CREATE INDEX IF NOT EXISTS idx_edges_file ON edges(file_id);

-- Import records
CREATE TABLE IF NOT EXISTS imports (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id         INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    import_line     INTEGER NOT NULL,
    module_path     TEXT NOT NULL,
    imported_names  TEXT,
    import_type     TEXT NOT NULL,
    is_used         INTEGER NOT NULL DEFAULT 0,
    used_at_lines   TEXT
);

CREATE INDEX IF NOT EXISTS idx_imports_file ON imports(file_id);
CREATE INDEX IF NOT EXISTS idx_imports_used ON imports(is_used);

-- Warnings
CREATE TABLE IF NOT EXISTS warnings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id         INTEGER REFERENCES files(id) ON DELETE CASCADE,
    node_id         INTEGER REFERENCES nodes(id) ON DELETE SET NULL,
    warn_type       TEXT NOT NULL,
    severity        TEXT NOT NULL DEFAULT 'warning',
    message         TEXT NOT NULL,
    line            INTEGER,
    details         TEXT
);

CREATE INDEX IF NOT EXISTS idx_warnings_file ON warnings(file_id);
CREATE INDEX IF NOT EXISTS idx_warnings_type ON warnings(warn_type);

-- Graph snapshots
CREATE TABLE IF NOT EXISTS graph_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_time   TEXT NOT NULL,
    entry_file      TEXT,
    entry_line      INTEGER,
    entry_type      TEXT,
    node_count      INTEGER NOT NULL DEFAULT 0,
    variable_count  INTEGER NOT NULL DEFAULT 0,
    edge_count      INTEGER NOT NULL DEFAULT 0,
    warning_count   INTEGER NOT NULL DEFAULT 0,
    is_dead_code    INTEGER NOT NULL DEFAULT 0,
    is_unreachable  INTEGER NOT NULL DEFAULT 1,
    root_node_ids   TEXT,
    component_hash  TEXT
);

CREATE INDEX IF NOT EXISTS idx_snapshots_time ON graph_snapshots(snapshot_time);

-- Component members: maps node_id to component_id for incremental connectivity analysis
CREATE TABLE IF NOT EXISTS component_members (
    component_id    INTEGER NOT NULL,
    node_id         INTEGER NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
    PRIMARY KEY (component_id, node_id)
);

CREATE INDEX IF NOT EXISTS idx_comp_members_comp ON component_members(component_id);
CREATE INDEX IF NOT EXISTS idx_comp_members_node ON component_members(node_id);

-- Composite index: speed up edge-type filtered queries by (source_id, edge_type) for reachability analysis
CREATE INDEX IF NOT EXISTS idx_edges_source_type ON edges(source_id, edge_type);

-- Composite index: speed up reverse lookup by (target_id, edge_type) for dead-code test reference queries
CREATE INDEX IF NOT EXISTS idx_edges_target_type ON edges(target_id, edge_type);

-- Single-column index: speed up warnings JOIN queries by node_id
CREATE INDEX IF NOT EXISTS idx_warnings_node ON warnings(node_id);

-- Sorted index: speed up ORDER BY warning_count for list_graphs pagination
CREATE INDEX IF NOT EXISTS idx_snapshots_warnings ON graph_snapshots(warning_count);

-- Sorted index: speed up ORDER BY node_count for list_graphs pagination
CREATE INDEX IF NOT EXISTS idx_snapshots_nodes ON graph_snapshots(node_count);
"""


def create_tables(conn: sqlite3.Connection) -> None:
    """Execute DDL statements on a SQLite connection."""
    for pragma in (
        "PRAGMA journal_mode=WAL",
        "PRAGMA foreign_keys=ON",
        "PRAGMA synchronous=NORMAL",
    ):
        try:
            conn.execute(pragma)
        except Exception:
            pass
    # Execute DDL statements individually (avoid implicit transaction in executescript)
    for stmt in CREATE_TABLES_SQL.strip().split(";"):
        stmt = stmt.strip()
        if stmt:
            try:
                conn.execute(stmt)
            except Exception:
                pass
