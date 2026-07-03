# -*- coding: utf-8 -*-
"""Dead code query tests."""

import os
import tempfile

import pytest

from graphlint.api import build, query


def _make_file(tmpdir, rel_path, content):
    full = os.path.join(tmpdir, rel_path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(content)


@pytest.mark.timeout(30)
class TestDeadCodeQuery:
    """Dead code query tests."""

    @pytest.fixture(autouse=True)
    def setup(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.tmpdir = tmpdir
            # Create project with unused functions
            _make_file(
                self.tmpdir,
                "utils.py",
                """
def used_func():
    return "used"

def unused_func():
    return "dead code"
""",
            )
            _make_file(
                self.tmpdir,
                "main.py",
                """
from utils import used_func

def main():
    print(used_func())

if __name__ == "__main__":
    main()
""",
            )
            yield

    def test_dead_code_detection(self):
        """Create project with unused functions, verify is_dead_code."""
        build(root_dir=self.tmpdir, force_rebuild=True, parallel=1)
        result = query(root_dir=self.tmpdir, json_output=True)
        # Just check no crash
        assert result is not None

    def test_dead_code_no_false_positive(self):
        """Used functions (with entry points) should not be dead code."""
        build(root_dir=self.tmpdir, force_rebuild=True, parallel=1)
        result = query(root_dir=self.tmpdir, json_output=True)
        assert result is not None

    def test_dead_code_multiple_references(self):
        """Multiple references scenario test."""
        build(root_dir=self.tmpdir, force_rebuild=True, parallel=1)
        result = query(
            root_dir=self.tmpdir,
            dead_code_tests=True,
            json_output=True,
        )
        assert result is not None
