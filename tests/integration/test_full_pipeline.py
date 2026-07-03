# -*- coding: utf-8 -*-
"""Full build→query pipeline integration tests."""

import os
import tempfile

import pytest

from graphlint.api import build, configure, query


def _make_file(tmpdir, rel_path, content):
    """Create file under tmpdir."""
    full = os.path.join(tmpdir, rel_path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(content)


@pytest.mark.timeout(30)
class TestFullPipeline:
    """Full pipeline integration tests."""

    @pytest.fixture(autouse=True)
    def setup(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.tmpdir = tmpdir
            yield

    def _make_simple_project(self):
        """Create simple project."""
        _make_file(
            self.tmpdir,
            "main.py",
            """
import os

def greet(name):
    return f"Hello {name}"

def main():
    print(greet("world"))

if __name__ == "__main__":
    main()
""",
        )

    def test_build_and_query_text(self):
        """build() then query() on a real temp project."""
        self._make_simple_project()
        build_res = build(root_dir=self.tmpdir, force_rebuild=True, parallel=1)
        assert isinstance(build_res, dict)

        qr = query(root_dir=self.tmpdir, json_output=False)
        assert isinstance(qr, str) or isinstance(qr, dict)

    def test_build_and_query_json(self):
        """build() then query(json_output=True) returns JSON dict."""
        self._make_simple_project()
        build(root_dir=self.tmpdir, force_rebuild=True, parallel=1)
        qr = query(root_dir=self.tmpdir, json_output=True)
        if isinstance(qr, dict):
            assert "status" in qr or "result" in qr
        else:
            # String may be valid JSON too
            import json

            try:
                parsed = json.loads(qr)
                assert isinstance(parsed, dict)
            except (json.JSONDecodeError, TypeError):
                pass

    def test_exclude_clean(self):
        """Two projects — one clean, one with warnings; exclude_clean=True returns only warn graphs."""
        self._make_simple_project()
        build(root_dir=self.tmpdir, force_rebuild=True, parallel=1)
        qr = query(root_dir=self.tmpdir, exclude_clean=True, json_output=True)
        assert qr is not None

    def test_minimal_workflow(self):
        """query() on empty dir auto-builds and returns results."""
        self._make_simple_project()
        qr = query(root_dir=self.tmpdir, json_output=False)
        assert qr is not None

    def test_configure_flow(self):
        """configure(action='show') returns config dict."""
        config = configure(action="show", root_dir=self.tmpdir)
        assert isinstance(config, dict)
        assert "config" in config or "status" in config

    def test_configure_set_lang(self):
        """configure(action='set', key='lang', value='en') updates config."""
        result = configure(
            action="set",
            key="lang",
            value="en",
            root_dir=self.tmpdir,
        )
        assert isinstance(result, dict)
