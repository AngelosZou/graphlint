# -*- coding: utf-8 -*-
"""Warning collector and warning detection function tests."""

import pytest

from graphlint.analyzer._types import EdgeInfo, NodeInfo
from graphlint.analyzer.warnings import (
    WarningCollector,
    detect_file_too_large,
    detect_write_only_nodes,
)


@pytest.mark.timeout(30)
class TestWarningCollector:
    """WarningCollector black-box tests."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.wc = WarningCollector()

    def test_all_warning_types(self):
        """Add all 11 warning types, verify get_all returns all."""
        types = [
            "unused_import",
            "dynamic_import",
            "circular_ref",
            "syntax_error",
            "write_only",
            "deprecated_usage",
            "dead_code",
            "type_mismatch",
            "unresolved_ref",
            "unused_variable",
            "file_too_large",
        ]
        for t in types:
            self.wc.add(warn_type=t, message=f"Test {t}")
        all_warnings = self.wc.get_all()
        assert len(all_warnings) == 11
        returned_types = {w.warn_type for w in all_warnings}
        assert returned_types == set(types)

    def test_deduplication(self):
        """Same (type, file, line) added twice, dedup leaves one."""
        self.wc.add(warn_type="unused_import", file_path="/a.py", line=10)
        self.wc.add(warn_type="unused_import", file_path="/a.py", line=10)
        assert len(self.wc.get_all()) == 2
        self.wc.deduplicate()
        assert len(self.wc.get_all()) == 1

    def test_add_invalid_type(self):
        """Adding invalid warning type raises ValueError."""
        with pytest.raises(ValueError):
            self.wc.add(warn_type="invalid_type", message="test")


@pytest.mark.timeout(30)
class TestDetectFunctions:
    """Detection function black-box tests."""

    def test_detect_write_only_nodes(self):
        """Variable node with only WRITE edge produces write_only warning."""
        node = NodeInfo(
            id=1,
            name="x",
            node_type="variable",
            line_start=1,
            line_end=2,
            col_offset=0,
        )
        edge = EdgeInfo(
            source_id=2,
            target_id=1,
            edge_type="write",
            file_id=1,
            line=1,
            context="x = 5",
        )
        warnings = detect_write_only_nodes([node], [edge])
        assert len(warnings) == 1
        assert warnings[0].warn_type == "write_only"

    def test_detect_unused_variable(self):
        """Variable with no edges produces unused_variable warning."""
        node = NodeInfo(
            id=1,
            name="y",
            node_type="variable",
            line_start=3,
            line_end=4,
            col_offset=0,
        )
        warnings = detect_write_only_nodes([node], [])
        assert len(warnings) == 1
        assert warnings[0].warn_type == "unused_variable"

    def test_detect_normal_variable(self):
        """Variable with READ edge should not produce warning."""
        node = NodeInfo(
            id=1,
            name="z",
            node_type="variable",
            line_start=5,
            line_end=6,
            col_offset=0,
        )
        edge = EdgeInfo(
            source_id=2,
            target_id=1,
            edge_type="read",
            file_id=1,
            line=5,
            context="print(z)",
        )
        warnings = detect_write_only_nodes([node], [edge])
        assert len(warnings) == 0

    def test_detect_file_too_large(self):
        """File larger than max size should produce warning."""
        max_size_mb = 10
        file_size_bytes = max_size_mb * 1024 * 1024 + 1
        warning = detect_file_too_large("/big.py", file_size_bytes, max_size_mb)
        assert warning is not None
        assert warning.warn_type == "file_too_large"

    def test_detect_file_not_too_large(self):
        """File at or below max size should not produce warning."""
        max_size_mb = 10
        file_size_bytes = max_size_mb * 1024 * 1024
        warning = detect_file_too_large("/small.py", file_size_bytes, max_size_mb)
        assert warning is None

    def test_dunder_all_skipped(self):
        """Module-level __all__ should not produce unused_variable warning."""
        node = NodeInfo(
            id=1,
            name="__all__",
            node_type="variable",
            line_start=1,
            line_end=2,
            col_offset=0,
        )
        warnings = detect_write_only_nodes([node], [])
        assert len(warnings) == 0

    def test_dunder_version_skipped(self):
        """Module-level __version__ should not produce write_only warning."""
        node = NodeInfo(
            id=1,
            name="__version__",
            node_type="variable",
            line_start=1,
            line_end=2,
            col_offset=0,
        )
        edge = EdgeInfo(
            source_id=2,
            target_id=1,
            edge_type="write",
            file_id=1,
            line=1,
            context='__version__ = "0.1.0"',
        )
        warnings = detect_write_only_nodes([node], [edge])
        assert len(warnings) == 0
