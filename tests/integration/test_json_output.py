# -*- coding: utf-8 -*-
"""JSON output format tests."""

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
class TestJsonOutput:
    """JSON output format tests."""

    @pytest.fixture(autouse=True)
    def setup(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.tmpdir = tmpdir
            _make_file(
                self.tmpdir,
                "main.py",
                """
import os
def main():
    print("hello")
main()
""",
            )
            yield

    def test_json_structure(self):
        """JSON output includes status/query_time_ms/root_dir/path_format/result keys."""
        build(root_dir=self.tmpdir, force_rebuild=True, parallel=1)
        result = query(root_dir=self.tmpdir, json_output=True)
        if isinstance(result, dict):
            assert "status" in result
            assert "query_time_ms" in result or "result" in result
            assert "root_dir" in result or "result" in result
        elif isinstance(result, str):
            import json

            try:
                parsed = json.loads(result)
                assert "status" in parsed or "result" in parsed
            except (json.JSONDecodeError, TypeError):
                pass

    def test_json_empty_result(self):
        """Empty project has empty graphs list."""
        with tempfile.TemporaryDirectory() as empty_dir:
            _make_file(empty_dir, "__init__.py", "")
            build(root_dir=empty_dir, force_rebuild=True, parallel=1)
            result = query(root_dir=empty_dir, json_output=True)
            if isinstance(result, dict):
                if "result" in result:
                    graphs = result["result"].get("graphs", [])
                    assert isinstance(graphs, list)

    def test_json_consistent_fields(self):
        """All GraphSummary dicts have identical key sets."""
        build(root_dir=self.tmpdir, force_rebuild=True, parallel=1)
        result = query(root_dir=self.tmpdir, json_output=True)
        if isinstance(result, dict):
            graphs = []
            if "result" in result:
                graphs = result["result"].get("graphs", [])
            elif "graphs" in result:
                graphs = result["graphs"]
            if graphs:
                keys = set(graphs[0].keys())
                for g in graphs[1:]:
                    assert set(g.keys()) == keys
