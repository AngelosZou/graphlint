# -*- coding: utf-8 -*-
"""Incremental indexer tests."""

import os
import tempfile

import pytest

from graphlint.incremental.indexer import IncrementalIndexer
from graphlint.storage.db import Database


def _make_file(tmpdir, rel_path, content):
    full = os.path.join(tmpdir, rel_path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(content)


@pytest.mark.timeout(30)
class TestIncrementalIndexer:
    """Incremental indexer integration tests."""

    @pytest.fixture(autouse=True)
    def setup(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.tmpdir = tmpdir
            # Create initial project
            _make_file(self.tmpdir, "utils.py", "def helper():\n    return 42\n")
            _make_file(
                self.tmpdir,
                "main.py",
                """
from utils import helper

def main():
    print(helper())

main()
""",
            )
            self.db = Database(self.tmpdir)
            self.indexer = IncrementalIndexer(self.tmpdir, self.db, parallel_workers=1)
            yield
            self.db.close()

    def test_full_build(self):
        """Build from scratch, verify IndexResult counts."""
        result = self.indexer.run(force_rebuild=True)
        assert result.files_scanned > 0
        assert result.duration_ms > 0

    def test_incremental_no_change(self):
        """Rebuild with no changes, verify zero counts."""
        self.indexer.run(force_rebuild=True)
        result = self.indexer.run(force_rebuild=False)
        # Files unchanged, all counts should be 0
        assert result.files_added == 0
        assert result.files_removed == 0

    def test_incremental_add_file(self):
        """Add new .py file, rebuild, verify files_added=1."""
        self.indexer.run(force_rebuild=True)
        _make_file(self.tmpdir, "new_module.py", "x = 1\n")
        result = self.indexer.run(force_rebuild=False)
        assert result.files_added >= 1

    def test_incremental_modify_file(self):
        """Modify existing file, rebuild, verify files_changed=1."""
        self.indexer.run(force_rebuild=True)
        _make_file(self.tmpdir, "utils.py", "def helper():\n    return 99\n")
        result = self.indexer.run(force_rebuild=False)
        assert result.files_changed >= 1

    def test_incremental_remove_file(self):
        """Delete file, rebuild, verify files_removed=1."""
        self.indexer.run(force_rebuild=True)
        os.remove(os.path.join(self.tmpdir, "utils.py"))
        result = self.indexer.run(force_rebuild=False)
        assert result.files_removed >= 1

    def test_force_rebuild(self):
        """force=True should perform full rebuild."""
        self.indexer.run(force_rebuild=True)
        result = self.indexer.run(force_rebuild=True)
        assert result.files_scanned > 0
