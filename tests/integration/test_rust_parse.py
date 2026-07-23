# -*- coding: utf-8 -*-
"""Integration tests for Rust source parsing via tree-sitter."""

import os
import tempfile

import pytest

from graphlint.analyzer.language.rust.constants import _TREE_SITTER_AVAILABLE
from graphlint.api import build, query


def _make_file(tmpdir, rel_path, content):
    """Create file under tmpdir."""
    full = os.path.join(tmpdir, rel_path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(content)


@pytest.mark.skipif(
    not _TREE_SITTER_AVAILABLE,
    reason="tree-sitter-rust not installed (pip install graphlint[rust])",
)
@pytest.mark.timeout(30)
class TestRustParse:
    """Verify Rust source files are parsed into graph nodes."""

    @pytest.fixture(autouse=True)
    def setup(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self.tmpdir = tmpdir
            yield

    def test_parse_simple_fn_main(self):
        """A single 'fn main() {}' produces at least one node."""
        _make_file(
            self.tmpdir,
            "main.rs",
            "fn main() {}\n",
        )
        result = build(root_dir=self.tmpdir, force_rebuild=True)
        assert result["status"] == "ok"
        assert result["files_scanned"] >= 1
        assert result["nodes_added"] >= 1, (
            f"No nodes created for Rust file — "
            f"tree-sitter grammar version may be incompatible. "
            f"Got {result['nodes_added']} nodes from {result['files_scanned']} files."
        )

    def test_parse_project_with_entry(self):
        """A Rust project with main() is not flagged as dead code."""
        _make_file(
            self.tmpdir,
            "main.rs",
            "fn main() {\n    hello();\n}\n\nfn hello() {\n    println!(\"hello\");\n}\n",
        )
        build(root_dir=self.tmpdir, force_rebuild=True)
        q = query(
            root_dir=self.tmpdir,
            warn_types="dead_code",
            json_output=True,
        )
        result = q.get("result", {})
        dead = result.get("warnings_summary", {}).get("dead_code", 0)
        assert dead == 0, (
            f"Expected 0 dead code for complete Rust project, got {dead}. "
            f"Entry point detection (fn main) may be failing."
        )
