"""
Mean-reversion strategy -- Phase 9.

Only fires when app.regime.detector classifies the regime as RANGING --
buying near the lower Bollinger Band and selling near the upper one is
trend.py's worst nightmare (a real breakout runs the band, not reverts
to it), so this deliberately requires the opposite of trend.py's gate.
"""
from __future__ import annotations

from typing import Optional

from app.analysis import indicators
from app.analysis.indicators import InsufficientDataError
from app.regime.detector import TrendState
from app.strategy.models import StrategyContext, StrategyName, StrategySignal

BB_WINDOW = 20
ATR_WINDOW = 14
ATR_STOP_BUFFER = 1.0
MIN_TARGET_DISTANCE_ATR = 0.25  # skip a signal too degenerate to be worth taking


def generate(context: StrategyContext) -> Optional[StrategySignal]:
    if context.regime.trend != TrendState.RANGING:
        return None
    try:
        bands = indicators.bollinger_bands(context.candles, window=BB_WINDOW)
        atr_values = indicators.atr(context.candles, window=ATR_WINDOW)
    except InsufficientDataError:
        return None

    close = context.candles[-1].close
    latest_atr = atr_values[-1]
    upper, lower, middle = bands.upper[-1], bands.lower[-1], bands.middle[-1]

    if close <= lower:
        side = "BUY"
        entry = close
        stop = min(context.candles[-1].low, lower) - latest_atr * ATR_STOP_BUFFER
        target = middle
    elif close >= upper:
        side = "SELL"
        entry = close
        stop = max(context.candles[-1].high, upper) + latest_atr * ATR_STOP_BUFFER
        target = middle
    else:
        return None

    if abs(target - entry) < latest_atr * MIN_TARGET_DISTANCE_ATR:
        return None  # bands collapsed too tight for target to mean anything

    return StrategySignal(
        strategy=StrategyName.MEAN_REVERSION,
        symbol=context.symbol,
        side=side,
        entry_price=entry,
        stop_loss=stop,
        target=target,
        confidence=min(1.0, context.regime.atr_pct_percentile / 100.0 * 0.5 + 0.3),
        reason=(
            f"RANGING regime, close {close:.2f} {'<= lower' if side == 'BUY' else '>= upper'} "
            f"Bollinger({BB_WINDOW}) band ({lower:.2f}/{upper:.2f}), targeting mean {middle:.2f}."
        ),
    )


__all__ = ["generate"]
