# -*- coding: utf-8 -*-
"""Output volume strategy decision maker."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class VolumeThresholds:
    """Output volume thresholds."""

    LOW_WATERMARK: int = 3000
    HIGH_WATERMARK: int = 8000


@dataclass
class OutputPlan:
    """Output plan."""

    mode: str = "full"  # full | index | truncated
    estimated_chars: int = 0
    skipped_count: int = 0
    skipped_large_count: int = 0


class VolumeStrategy:
    """Adaptive output volume strategy."""

    def __init__(self, thresholds: Optional[VolumeThresholds] = None) -> None:
        self.thresholds = thresholds or VolumeThresholds()

    def decide(
        self,
        graphs: list[Any],
        json_mode: bool = False,
        output_limit: int = 8000,
        detail_level: str = "auto",
    ) -> OutputPlan:
        """Decide the output strategy."""
        if json_mode:
            return OutputPlan(mode="full", estimated_chars=0)

        if detail_level == "summary":
            return OutputPlan(mode="index", estimated_chars=0)
        if detail_level == "full":
            return OutputPlan(mode="full", estimated_chars=0)
        if detail_level == "minimal":
            return OutputPlan(
                mode="index",
                estimated_chars=0,
                skipped_count=len(graphs),
                skipped_large_count=0,
            )

        # Auto mode
        estimated = sum(
            80 + 15 * getattr(g, "warning_count", 0) + len(getattr(g, "entry", ""))
            for g in graphs
        )
        limit = min(output_limit, self.thresholds.HIGH_WATERMARK)

        if estimated <= min(output_limit, self.thresholds.LOW_WATERMARK):
            return OutputPlan(mode="full", estimated_chars=estimated)

        if estimated <= limit:
            return OutputPlan(mode="index", estimated_chars=estimated)

        # Truncated mode: sort by warning count, take top results
        sorted_graphs = sorted(
            graphs, key=lambda g: len(getattr(g, "warnings", [])), reverse=True
        )
        kept = []
        current = 0
        for g in sorted_graphs:
            chars = (
                80 + 15 * len(getattr(g, "warnings", [])) + len(getattr(g, "entry", ""))
            )
            if current + chars <= output_limit:
                kept.append(g)
                current += chars
            else:
                break

        skipped = len(graphs) - len(kept)
        return OutputPlan(
            mode="truncated",
            estimated_chars=estimated,
            skipped_count=skipped,
            skipped_large_count=0,
        )
