"""
Breakout strategy -- Phase 9.

Looks for a close beyond the recent N-candle high/low (excluding the
current candle) following a volatility squeeze (Bollinger Band width
ranking in the tightest third of its own recent history) -- a
squeeze-then-expand pattern is a common, simple breakout heuristic, not
a claim it beats a random entry; see docs/PRINCIPLES.md on unvalidated
thresholds.
"""
from __future__ import annotations

from typing import Optional

from app.analysis import indicators
from app.analysis.indicators import InsufficientDataError
from app.analysis.stats import percentile_rank
from app.strategy.models import StrategyContext, StrategyName, StrategySignal
from app.strategy.sizing import atr_stop_and_target

LOOKBACK = 20
BB_WINDOW = 20
ATR_WINDOW = 14
SQUEEZE_PERCENTILE = 33.0  # latest BB width must rank in the tightest third of its own recent history
STOP_MULTIPLE = 1.0
REWARD_MULTIPLE = 2.0


def generate(context: StrategyContext) -> Optional[StrategySignal]:
    if len(context.candles) < LOOKBACK + 1:
        return None
    try:
        bands = indicators.bollinger_bands(context.candles, window=BB_WINDOW)
        atr_values = indicators.atr(context.candles, window=ATR_WINDOW)
    except InsufficientDataError:
        return None

    widths = [
        ((u - l) / m * 100) if m else 0.0
        for u, l, m in zip(bands.upper, bands.lower, bands.middle)
        if m == m  # drop NaN warm-up entries before BollingerBands' own window is satisfied
    ]
    if len(widths) < 2:
        return None
    latest_width = widths[-1]
    width_percentile = percentile_rank(widths[:-1], latest_width)
    if width_percentile > SQUEEZE_PERCENTILE:
        return None  # not currently squeezed -- this strategy only trades the breakout, not the range

    recent = context.candles[-(LOOKBACK + 1):-1]  # excludes the current candle
    recent_high = max(c.high for c in recent)
    recent_low = min(c.low for c in recent)
    close = context.candles[-1].close
    latest_atr = atr_values[-1]

    if close > recent_high:
        side = "BUY"
    elif close < recent_low:
        side = "SELL"
    else:
        return None

    stop, target = atr_stop_and_target(close, latest_atr, side, STOP_MULTIPLE, REWARD_MULTIPLE)
    return StrategySignal(
        strategy=StrategyName.BREAKOUT,
        symbol=context.symbol,
        side=side,
        entry_price=close,
        stop_loss=stop,
        target=target,
        confidence=0.5,  # squeeze-breakout patterns are notoriously prone to false breaks; kept modest
        reason=(
            f"BB width squeeze (percentile {width_percentile:.0f}) followed by close {close:.2f} "
            f"breaking {LOOKBACK}-bar {'high' if side == 'BUY' else 'low'} "
            f"({recent_high:.2f}/{recent_low:.2f})."
        ),
    )


__all__ = ["generate"]
