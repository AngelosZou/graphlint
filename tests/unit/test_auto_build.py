# -*- coding: utf-8 -*-
"""Tests for _auto_build and _scan_current."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# =============================================================================
# TEST-T11: _scan_current and _update_scan_stamp tests
# =============================================================================


@pytest.mark.timeout(30)
class TestScanCurrent:
    """Tests for _scan_current — single-scan change detection."""

    def test_no_stamp_file_returns_true(self, tmp_path: Path):
        """No .last_scan_stamp file should return (True, current_files)."""
        from graphlint.api import _scan_current

        stamp_dir = tmp_path / ".graphlint"
        assert not stamp_dir.exists()

        changed, files = _scan_current(str(tmp_path))
        assert changed is True, "No stamp file should return changed=True"
        assert isinstance(files, dict)

    def test_corrupted_stamp_file_returns_true(self, tmp_path: Path):
        """Corrupted .last_scan_stamp file should return changed=True."""
        from graphlint.api import _scan_current

        stamp_dir = tmp_path / ".graphlint"
        stamp_dir.mkdir(parents=True, exist_ok=True)
        stamp_file = stamp_dir / ".last_scan_stamp"
        stamp_file.write_text("invalid json content{{{", encoding="utf-8")

        changed, files = _scan_current(str(tmp_path))
        assert changed is True, "Corrupted stamp file should return changed=True"
        assert isinstance(files, dict)

    def test_no_changes_returns_false(self, tmp_path: Path):
        """Correct snapshot with no file changes should return changed=False."""
        from graphlint.api import _scan_current

        src_file = tmp_path / "main.py"
        src_file.write_text("print('hello')", encoding="utf-8")
        mtime = os.stat(str(src_file)).st_mtime_ns

        stamp_dir = tmp_path / ".graphlint"
        stamp_dir.mkdir(parents=True, exist_ok=True)
        stamp_file = stamp_dir / ".last_scan_stamp"
        stamp_file.write_text(
            json.dumps({"files": {"main.py": mtime}}),
            encoding="utf-8",
        )

        changed, files = _scan_current(str(tmp_path))
        assert changed is False, "No changes should return changed=False"
        assert files == {"main.py": mtime}

    def test_modified_file_returns_true(self, tmp_path: Path):
        """Modified file should return changed=True."""
        from graphlint.api import _scan_current

        src_file = tmp_path / "main.py"
        src_file.write_text("print('hello')", encoding="utf-8")
        old_mtime = os.stat(str(src_file)).st_mtime_ns

        stamp_dir = tmp_path / ".graphlint"
        stamp_dir.mkdir(parents=True, exist_ok=True)
        stamp_file = stamp_dir / ".last_scan_stamp"
        stamp_file.write_text(
            json.dumps({"files": {"main.py": old_mtime}}),
            encoding="utf-8",
        )

        import time
        time.sleep(0.05)
        src_file.write_text("print('world')", encoding="utf-8")
        new_mtime = os.stat(str(src_file)).st_mtime_ns
        assert new_mtime != old_mtime

        changed, files = _scan_current(str(tmp_path))
        assert changed is True, "Modified file should return changed=True"
        assert "main.py" in files
        assert files["main.py"] == new_mtime

    def test_deleted_file_returns_true(self, tmp_path: Path):
        """Deleted file should return changed=True."""
        from graphlint.api import _scan_current

        src_file = tmp_path / "main.py"
        src_file.write_text("print('hello')", encoding="utf-8")
        old_mtime = os.stat(str(src_file)).st_mtime_ns

        stamp_dir = tmp_path / ".graphlint"
        stamp_dir.mkdir(parents=True, exist_ok=True)
        stamp_file = stamp_dir / ".last_scan_stamp"
        stamp_file.write_text(
            json.dumps({"files": {"main.py": old_mtime}}),
            encoding="utf-8",
        )

        src_file.unlink()

        changed, files = _scan_current(str(tmp_path))
        assert changed is True, "Deleted file should return changed=True"
        assert "main.py" not in files

    def test_new_file_returns_true(self, tmp_path: Path):
        """New file should return changed=True."""
        from graphlint.api import _scan_current

        stamp_dir = tmp_path / ".graphlint"
        stamp_dir.mkdir(parents=True, exist_ok=True)
        stamp_file = stamp_dir / ".last_scan_stamp"
        stamp_file.write_text(
            json.dumps({"files": {}}),
            encoding="utf-8",
        )

        src_file = tmp_path / "new.py"
        src_file.write_text("print('new')", encoding="utf-8")

        changed, files = _scan_current(str(tmp_path))
        assert changed is True, "New file should return changed=True"
        assert "new.py" in files

    def test_ignores_non_py_files(self, tmp_path: Path):
        """Non-.py file changes should not trigger change detection."""
        from graphlint.api import _scan_current

        py_file = tmp_path / "main.py"
        py_file.write_text("print('hello')", encoding="utf-8")
        mtime = os.stat(str(py_file)).st_mtime_ns

        stamp_dir = tmp_path / ".graphlint"
        stamp_dir.mkdir(parents=True, exist_ok=True)
        stamp_file = stamp_dir / ".last_scan_stamp"
        stamp_file.write_text(
            json.dumps({"files": {"main.py": mtime}}),
            encoding="utf-8",
        )

        txt_file = tmp_path / "notes.txt"
        txt_file.write_text("some notes", encoding="utf-8")

        changed, files = _scan_current(str(tmp_path))
        assert changed is False, "Non-.py file changes should not affect result"
        assert "notes.txt" not in files


@pytest.mark.timeout(30)
class TestUpdateScanStamp:
    """Tests for _update_scan_stamp function."""

    def test_creates_stamp_file(self, tmp_path: Path):
        """Verify _update_scan_stamp creates stamp file."""
        from graphlint.incremental.indexer import IncrementalIndexer
        from graphlint.storage.db import Database

        db = Database(str(tmp_path))
        try:
            indexer = IncrementalIndexer(str(tmp_path), db, 0)

            # Create some .py files
            (tmp_path / "a.py").write_text("import b", encoding="utf-8")
            (tmp_path / "b.py").write_text("x = 1", encoding="utf-8")

            # Call _update_scan_stamp
            indexer._update_scan_stamp(["a.py", "b.py"])

            stamp_path = tmp_path / ".graphlint" / ".last_scan_stamp"
            assert stamp_path.exists(), "Stamp file should be created"

            # Verify content is valid JSON
            content = stamp_path.read_text(encoding="utf-8")
            data = json.loads(content)
            assert "files" in data
            assert "a.py" in data["files"]
            assert "b.py" in data["files"]
            # Verify mtime_ns is integer
            assert isinstance(data["files"]["a.py"], int)
        finally:
            db.close()

    def test_empty_files_list(self, tmp_path: Path):
        """Verify empty file list creates valid stamp file."""
        from graphlint.incremental.indexer import IncrementalIndexer
        from graphlint.storage.db import Database

        db = Database(str(tmp_path))
        try:
            indexer = IncrementalIndexer(str(tmp_path), db, 0)
            indexer._update_scan_stamp([])

            stamp_path = tmp_path / ".graphlint" / ".last_scan_stamp"
            assert stamp_path.exists()
            data = json.loads(stamp_path.read_text(encoding="utf-8"))
            assert data == {"files": {}, "public_as_entry": False}
        finally:
            db.close()


@pytest.mark.timeout(30)
class TestAutoBuildIntegration:
    """Integration tests: simulate _auto_build flow."""

    def test_auto_build_first_run_creates_db(self, tmp_path: Path):
        """First run (no stamp) should create Database."""
        from graphlint.api import _auto_build

        (tmp_path / "main.py").write_text("x = 1", encoding="utf-8")

        with patch("graphlint.api.Database") as mock_db:
            mock_db_instance = MagicMock()
            mock_db.return_value = mock_db_instance

            result = _auto_build(str(tmp_path), {})
            assert result is True
            mock_db.assert_called_once()

    def test_auto_build_no_change_skips_db(self, tmp_path: Path):
        """When stamp matches, _auto_build should skip DB creation."""
        from graphlint.api import _auto_build

        (tmp_path / "main.py").write_text("x = 1", encoding="utf-8")
        mtime = os.stat(str(tmp_path / "main.py")).st_mtime_ns

        stamp_dir = tmp_path / ".graphlint"
        stamp_dir.mkdir(parents=True, exist_ok=True)
        (stamp_dir / ".last_scan_stamp").write_text(
            json.dumps({"files": {"main.py": mtime}}),
            encoding="utf-8",
        )

        with patch("graphlint.api.Database") as mock_db:
            result = _auto_build(str(tmp_path), {})
            assert result is True
            mock_db.assert_not_called()

    def test_auto_build_with_changes(self, tmp_path: Path):
        """Verify file changes trigger DB creation."""
        from graphlint.api import _auto_build

        stamp_dir = tmp_path / ".graphlint"
        stamp_dir.mkdir(parents=True, exist_ok=True)
        (stamp_dir / ".last_scan_stamp").write_text(
            json.dumps({"files": {"old.py": 12345}}),
            encoding="utf-8",
        )

        (tmp_path / "main.py").write_text("x = 1", encoding="utf-8")

        with patch("graphlint.api.Database") as mock_db:
            mock_db_instance = MagicMock()
            mock_db.return_value = mock_db_instance

            _auto_build(str(tmp_path), {})
            mock_db.assert_called_once()
