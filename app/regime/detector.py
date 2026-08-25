"""
Market regime detection -- Phase 7.

Classifies recent price action into a trend state (trending up/down vs.
ranging) and a volatility state (low/normal/high), built entirely on top
of Phase 6's indicators (ADX for trend strength/direction, ATR for
volatility). Nothing here decides whether to trade -- this is
descriptive context the Strategy Engine (Phase 9) is expected to use to
pick which strategy family applies (e.g. trend-following when TRENDING,
mean-reversion when RANGING), same as every analysis-layer module in
this project (spec section 47, docs/PRINCIPLES.md section 1).

Volatility is classified by percentile rank of ATR-as-%-of-close within
its own recent history, not a fixed absolute threshold -- "high
volatility" means something very different for a ₹50 stock than for
NIFTY, and a fixed cutoff picked once would silently misclassify
whichever instruments it wasn't tuned for.

The trend ADX threshold and volatility percentile cutoffs below are
defensible starting points, not calibrated against real trading
outcomes -- treat them the same way as docs/ACCEPTANCE_CRITERIA.md's
numbers: provisional until reviewed against actual data for the
instruments this trades.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import List

from app.analysis import indicators
from app.analysis.indicators import InsufficientDataError
from app.data.models import Candle


class TrendState(str, Enum):
    TRENDING_UP = "TRENDING_UP"
    TRENDING_DOWN = "TRENDING_DOWN"
    RANGING = "RANGING"


class VolatilityState(str, Enum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"


@dataclass(frozen=True)
class RegimeSnapshot:
    trend: TrendState
    volatility: VolatilityState
    adx: float
    plus_di: float
    minus_di: float
    atr_pct: float
    atr_pct_percentile: float  # 0-100: where the latest atr_pct ranks in its own recent history


def _percentile_rank(history: List[float], value: float) -> float:
    """Percentage of `history` that is <= `value`. 0-100. Falls back to
    the neutral midpoint (NORMAL-classifying) when there's no history to
    rank against, rather than raising for what is often just a short
    candle list rather than a real error."""
    if not history:
        return 50.0
    below_or_equal = sum(1 for v in history if v <= value)
    return 100.0 * below_or_equal / len(history)


def detect_regime(
    candles: List[Candle],
    adx_window: int = 14,
    atr_window: int = 14,
    trend_threshold: float = 25.0,
    low_volatility_percentile: float = 33.0,
    high_volatility_percentile: float = 67.0,
) -> RegimeSnapshot:
    """Classify the regime as of the most recent candle.

    Needs enough candles for ADX to warm up (`adx_window * 2`, the same
    requirement `app.analysis.indicators.adx` itself enforces) -- raises
    InsufficientDataError (via that call) if there aren't enough.
    """
    adx_result = indicators.adx(candles, window=adx_window)  # raises InsufficientDataError itself
    atr_values = indicators.atr(candles, window=atr_window)  # raises InsufficientDataError itself
    closes = [c.close for c in candles]

    # ta's AverageTrueRange leaves the first (atr_window - 1) entries as
    # literal 0.0 while it warms up (not NaN -- checked against the
    # installed source, see app/analysis/indicators.py's own header).
    # Excluded here so they don't pollute the volatility percentile
    # distribution as fake "zero volatility" data points.
    warm_up = atr_window - 1
    atr_pct_series = [
        (a / c) * 100 if c else 0.0
        for a, c in zip(atr_values[warm_up:], closes[warm_up:])
    ]
    if not atr_pct_series:
        raise InsufficientDataError("Not enough candles to compute a volatility reading.")

    latest_adx = adx_result.adx[-1]
    latest_plus_di = adx_result.plus_di[-1]
    latest_minus_di = adx_result.minus_di[-1]
    latest_atr_pct = atr_pct_series[-1]

    if latest_adx >= trend_threshold:
        trend = TrendState.TRENDING_UP if latest_plus_di >= latest_minus_di else TrendState.TRENDING_DOWN
    else:
        trend = TrendState.RANGING

    percentile = _percentile_rank(atr_pct_series[:-1], latest_atr_pct)
    if percentile <= low_volatility_percentile:
        volatility = VolatilityState.LOW
    elif percentile >= high_volatility_percentile:
        volatility = VolatilityState.HIGH
    else:
        volatility = VolatilityState.NORMAL

    return RegimeSnapshot(
        trend=trend,
        volatility=volatility,
        adx=latest_adx,
        plus_di=latest_plus_di,
        minus_di=latest_minus_di,
        atr_pct=latest_atr_pct,
        atr_pct_percentile=percentile,
    )


__all__ = ["TrendState", "VolatilityState", "RegimeSnapshot", "detect_regime"]
