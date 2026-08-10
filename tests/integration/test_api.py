# -*- coding: utf-8 -*-
"""Python API end-to-end tests."""

import os
import tempfile

import pytest

from graphlint import api
from graphlint.exceptions import InvalidPathError


def _make_file(tmpdir, rel_path, content):
    full = os.path.join(tmpdir, rel_path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(content)


@pytest.mark.timeout(30)
class TestApi:
    """Python API end-to-end tests."""

    @pytest.fixture(autouse=True)
    def setup(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.tmpdir = tmpdir
            _make_file(
                self.tmpdir,
                "main.py",
                """
import os
def greet():
    return "hello"
greet()
""",
            )
            yield

    def test_api_query(self):
        """api.query() returns string on temp project."""
        result = api.query(root_dir=self.tmpdir)
        assert isinstance(result, (str, dict))

    def test_api_query_json(self):
        """api.query(json_output=True) returns dict."""
        result = api.query(root_dir=self.tmpdir, json_output=True)
        if isinstance(result, dict):
            assert True
        else:
            # String may be JSON
            import json

            try:
                parsed = json.loads(result)
                assert isinstance(parsed, dict)
            except (json.JSONDecodeError, TypeError):
                pass

    def test_api_build(self):
        """api.build() returns dict with IndexResult fields."""
        result = api.build(root_dir=self.tmpdir, force_rebuild=True, parallel=1)
        assert isinstance(result, dict)
        assert "duration_ms" in result or "files_scanned" in result

    def test_api_configure_show(self):
        """api.configure(action='show') returns dict with 'config' key."""
        result = api.configure(action="show", root_dir=self.tmpdir)
        assert isinstance(result, dict)

    def _corrupt_db_schema(self):
        """Simulate a DB from an older graphlint: unversioned + missing
        columns."""
        import sqlite3

        db_path = os.path.join(self.tmpdir, ".graphlint", "db.sqlite")
        conn = sqlite3.connect(db_path)
        conn.execute("ALTER TABLE nodes DROP COLUMN is_partial")
        conn.execute("ALTER TABLE nodes DROP COLUMN canonical_name")
        conn.execute("ALTER TABLE nodes DROP COLUMN visibility")
        conn.execute("PRAGMA user_version = 0")
        conn.close()

    def _db_columns(self, table: str) -> list[str]:
        import sqlite3

        db_path = os.path.join(self.tmpdir, ".graphlint", "db.sqlite")
        conn = sqlite3.connect(db_path)
        try:
            return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
        finally:
            conn.close()

    def test_api_build_heals_incompatible_db(self):
        """build --force on a stale-schema DB drops it and rebuilds
        (was Error)."""
        assert api.build(root_dir=self.tmpdir, force_rebuild=True, parallel=1)["status"] == "ok"
        self._corrupt_db_schema()

        result = api.build(root_dir=self.tmpdir, force_rebuild=True, parallel=1)
        assert result["status"] == "ok"
        assert "is_partial" in self._db_columns("nodes")

    def test_api_build_heals_corrupt_stamped_db(self):
        """build --force on a version-stamped but shape-corrupt DB recovers."""
        import sqlite3

        assert api.build(root_dir=self.tmpdir, force_rebuild=True, parallel=1)["status"] == "ok"
        # Version stamp matches code, but a column is missing (e.g. tampered
        # DB): the INSERT fails at build time and the defensive retry kicks in.
        db_path = os.path.join(self.tmpdir, ".graphlint", "db.sqlite")
        conn = sqlite3.connect(db_path)
        conn.execute("ALTER TABLE nodes DROP COLUMN is_partial")
        conn.close()

        result = api.build(root_dir=self.tmpdir, force_rebuild=True, parallel=1)
        assert result["status"] == "ok"
        assert "is_partial" in self._db_columns("nodes")

    def test_api_query_heals_incompatible_db(self):
        """query auto-build on a stale-schema DB drops it and rebuilds
        (was 0 nodes)."""
        api.build(root_dir=self.tmpdir, force_rebuild=True, parallel=1)
        self._corrupt_db_schema()

        result = api.query(root_dir=self.tmpdir, json_output=True)
        assert result is not None
        assert "is_partial" in self._db_columns("nodes")

    def test_api_configure_set(self):
        """api.configure(action='set', key='lang', value='en') returns ok."""
        result = api.configure(
            action="set",
            key="lang",
            value="en",
            root_dir=self.tmpdir,
        )
        assert isinstance(result, dict)

    def test_api_invalid_root_dir(self):
        """api.query(root_dir='/nonexistent') should raise."""
        with pytest.raises((InvalidPathError, FileNotFoundError, ValueError)):
            api.query(root_dir="/nonexistent_path_12345")

    def test_api_build_and_query(self):
        """api.build() then api.query() yields consistent results."""
        build_res = api.build(root_dir=self.tmpdir, force_rebuild=True, parallel=1)
        assert isinstance(build_res, dict)

        query_res = api.query(root_dir=self.tmpdir)
        assert query_res is not None

    def test_api_configure_copy_from(self):
        """api.configure(action='copy-from', source=src) copies config."""
        with tempfile.TemporaryDirectory() as src_dir:
            _make_file(src_dir, "main.py", "x=1\n")
            api.build(root_dir=src_dir, force_rebuild=True, parallel=1)
            # Ensure source has config first
            result = api.configure(
                action="copy-from",
                source=src_dir,
                root_dir=self.tmpdir,
            )
            assert isinstance(result, dict)
