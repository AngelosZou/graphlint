# -*- coding: utf-8 -*-
"""SQLite database operations wrapper with concurrent write lock."""

from __future__ import annotations

import os
import sqlite3
import sys
from contextlib import contextmanager
from typing import Any, Optional

# fcntl 仅在 Unix 上可用
try:
    import fcntl
except ImportError:
    fcntl = None  # type: ignore[assignment]


class IndexLock:
    """Exclusive lock for concurrent writes."""

    def __init__(self, root_dir: str) -> None:
        """Initialize the lock."""
        self.lock_path: str = os.path.join(
            os.path.realpath(root_dir), ".graphlint", ".lock"
        )
        self._fd: Optional[Any] = None

    def __enter__(self) -> "IndexLock":
        """Acquire the exclusive lock."""
        os.makedirs(os.path.dirname(self.lock_path), exist_ok=True)
        self._fd = open(self.lock_path, "w")
        if sys.platform == "win32":
            import msvcrt

            msvcrt.locking(self._fd.fileno(), msvcrt.LK_LOCK, 1)
        elif fcntl is not None:
            fcntl.flock(self._fd, fcntl.LOCK_EX)
        return self

    def __exit__(self, *args: Any) -> None:
        """Release the lock."""
        if self._fd is not None:
            try:
                if sys.platform == "win32":
                    import msvcrt

                    msvcrt.locking(self._fd.fileno(), msvcrt.LK_UNLCK, 1)
                elif fcntl is not None:
                    fcntl.flock(self._fd, fcntl.LOCK_UN)
            except (OSError, ValueError):
                pass
            finally:
                self._fd.close()
                self._fd = None


class Database:
    """SQLite database operations wrapper with parameterized queries."""

    def __init__(self, root_dir: str) -> None:
        """Initialize the database connection."""
        real_root = os.path.realpath(root_dir)
        meta_dir = os.path.join(real_root, ".graphlint")
        os.makedirs(meta_dir, exist_ok=True)
        self.db_path: str = os.path.join(meta_dir, "db.sqlite")
        self.root_dir: str = real_root
        self.conn: sqlite3.Connection = sqlite3.connect(
            self.db_path,
            isolation_level=None,
        )
        self.conn.row_factory = sqlite3.Row
        # Set PRAGMAs before creating tables
        import sqlite3 as _sqlite3

        try:
            self.conn.execute("PRAGMA journal_mode=WAL")
        except _sqlite3.OperationalError:
            pass
        try:
            self.conn.execute("PRAGMA foreign_keys=ON")
        except _sqlite3.OperationalError:
            pass
        try:
            self.conn.execute("PRAGMA synchronous=NORMAL")
        except _sqlite3.OperationalError:
            pass
        from graphlint.storage.schema import create_tables

        create_tables(self.conn)

    # ------------------------------------------------------------------
    # Query methods (parameterized)
    # ------------------------------------------------------------------

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        """Execute a SQL statement with ? placeholders."""
        return self.conn.execute(sql, params)

    def executemany(
        self, sql: str, param_list: list[tuple[Any, ...]]
    ) -> sqlite3.Cursor:
        """Execute a SQL statement with multiple parameter sets."""
        return self.conn.executemany(sql, param_list)

    def fetchone(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
        """Execute query and return a single row."""
        cursor = self.execute(sql, params)
        result: sqlite3.Row | None = cursor.fetchone()
        return result

    def fetchall(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        """Execute query and return all rows."""
        cursor = self.execute(sql, params)
        return cursor.fetchall()

    # ------------------------------------------------------------------
    # Transaction management
    # ------------------------------------------------------------------

    def begin_transaction(self) -> None:
        """Begin a transaction using IMMEDIATE mode."""
        self.conn.execute("BEGIN IMMEDIATE")

    def commit(self) -> None:
        """Commit the transaction."""
        try:
            self.conn.commit()
        except sqlite3.OperationalError:
            pass

    def rollback(self) -> None:
        """Rollback the transaction."""
        try:
            self.conn.rollback()
        except sqlite3.OperationalError:
            pass

    @contextmanager
    def transaction(self) -> Any:
        """Transaction context manager."""
        self.begin_transaction()
        try:
            yield
            self.commit()
        except Exception:
            self.rollback()
            raise

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the database connection."""
        if self.conn:
            try:
                self.conn.execute("PRAGMA optimize")
                fc = self.conn.execute("PRAGMA freelist_count").fetchone()[0]
                pc = self.conn.execute("PRAGMA page_count").fetchone()[0]
                if pc > 0 and fc / pc > 0.2:
                    self.conn.execute("VACUUM")
            except Exception:
                pass
            self.conn.close()
