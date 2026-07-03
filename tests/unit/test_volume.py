# -*- coding: utf-8 -*-
"""Output volume strategy decision tests."""

from dataclasses import dataclass

import pytest

from graphlint.query.volume import VolumeStrategy


@dataclass
class FakeGraphSummary:
    """Mock GraphSummary for testing."""

    warning_count: int = 0
    entry: str = ""
    warnings: list = None

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = [1] * self.warning_count


@pytest.mark.timeout(30)
class TestVolumeStrategy:
    """VolumeStrategy black-box tests."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.strategy = VolumeStrategy()

    def test_full_mode_small(self):
        """2 graphs with 5 warnings each, estimate < 3000 → full mode."""
        graphs = [
            FakeGraphSummary(warning_count=5, entry="mod1"),
            FakeGraphSummary(warning_count=5, entry="mod2"),
        ]
        plan = self.strategy.decide(graphs)
        assert plan.mode == "full"

    def test_index_mode_medium(self):
        """20 graphs with 10 warnings each, estimate > 3000 → index mode."""
        graphs = [
            FakeGraphSummary(warning_count=10, entry=f"mod{i}") for i in range(20)
        ]
        plan = self.strategy.decide(graphs)
        assert plan.mode == "index"

    def test_truncated_mode_large(self):
        """100 graphs with 20 warnings each, estimate > 8000 → truncated mode."""
        graphs = [
            FakeGraphSummary(warning_count=20, entry=f"mod{i}") for i in range(100)
        ]
        plan = self.strategy.decide(graphs)
        assert plan.mode == "truncated"
        assert plan.skipped_count > 0

    def test_json_mode_no_truncation(self):
        """json=True always returns full mode."""
        graphs = [FakeGraphSummary(warning_count=20, entry="mod") for _ in range(100)]
        plan = self.strategy.decide(graphs, json_mode=True)
        assert plan.mode == "full"

    def test_detail_override_summary(self):
        """detail_level='summary' forces index mode."""
        graphs = [FakeGraphSummary(warning_count=1)]
        plan = self.strategy.decide(graphs, detail_level="summary")
        assert plan.mode == "index"

    def test_detail_override_full(self):
        """detail_level='full' forces full mode."""
        graphs = [FakeGraphSummary(warning_count=20) for _ in range(100)]
        plan = self.strategy.decide(graphs, detail_level="full")
        assert plan.mode == "full"

    def test_detail_minimal(self):
        """detail_level='minimal' → minimal mode."""
        graphs = [FakeGraphSummary(warning_count=1)]
        plan = self.strategy.decide(graphs, detail_level="minimal")
        assert plan.mode == "index"
        assert plan.skipped_count == len(graphs)

    def test_output_limit(self):
        """Custom output_limit=500 causes earlier truncation."""
        graphs = [FakeGraphSummary(warning_count=5, entry=f"mod{i}") for i in range(50)]
        plan = self.strategy.decide(graphs, output_limit=500)
        assert plan.mode in ("index", "truncated")

    def test_empty_graphs(self):
        """Empty list returns full mode."""
        plan = self.strategy.decide([])
        assert plan.mode == "full"
        assert plan.estimated_chars == 0

    def test_auto_decision_threshold_boundary(self):
        """Threshold boundary: just <= LOW_WATERMARK → full."""
        # Each graph ~80 + 15*5 = 155 chars, 19 graphs ~2945 chars < 3000
        graphs = [FakeGraphSummary(warning_count=5, entry="x") for _ in range(19)]
        plan = self.strategy.decide(graphs)
        assert plan.mode == "full"

        # 20 graphs ~3100 chars > 3000
        graphs2 = [FakeGraphSummary(warning_count=5, entry="x") for _ in range(20)]
        plan2 = self.strategy.decide(graphs2)
        assert plan2.mode in ("index", "truncated")
