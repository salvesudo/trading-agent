"""
Small shared statistics helpers -- used by multiple analysis-layer
modules that each need to rank a fresh reading against its own recent
history (app/regime/detector.py's volatility percentile, Phase 9's
breakout squeeze detection). Extracted here instead of duplicated once
a second caller needed the exact same logic.
"""
from __future__ import annotations

from typing import List


def percentile_rank(history: List[float], value: float) -> float:
    """Percentage of `history` that is <= `value`. 0-100. Returns the
    neutral midpoint (50.0) when there's no history to rank against,
    rather than raising for what is usually just a short input."""
    if not history:
        return 50.0
    below_or_equal = sum(1 for v in history if v <= value)
    return 100.0 * below_or_equal / len(history)


__all__ = ["percentile_rank"]
