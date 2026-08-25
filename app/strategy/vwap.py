"""
VWAP strategy -- Phase 9.

Simple pullback-to-VWAP-with-the-trend rule: price returning close to
the session VWAP while the regime still favors the prevailing direction
-- entering there rather than chasing an extended move. Uses
app.analysis.indicators.vwap, added in this same phase specifically for
this strategy.
"""
from __future__ import annotations

from typing import Optional

from app.analysis import indicators
from app.analysis.indicators import InsufficientDataError
from app.regime.detector import TrendState
from app.strategy.models import StrategyContext, StrategyName, StrategySignal
from app.strategy.sizing import atr_stop_and_target

ATR_WINDOW = 14
PULLBACK_ATR_TOLERANCE = 0.5  # how close to VWAP counts as "at" VWAP
STOP_MULTIPLE = 1.0
REWARD_MULTIPLE = 2.0


def generate(context: StrategyContext) -> Optional[StrategySignal]:
    if context.regime.trend == TrendState.RANGING:
        return None
    try:
        vwap_values = indicators.vwap(context.candles)
        atr_values = indicators.atr(context.candles, window=ATR_WINDOW)
    except InsufficientDataError:
        return None

    close = context.candles[-1].close
    latest_vwap = vwap_values[-1]
    latest_atr = atr_values[-1]
    distance = abs(close - latest_vwap)

    if distance > latest_atr * PULLBACK_ATR_TOLERANCE:
        return None  # not currently near VWAP -- no pullback entry available right now

    if context.regime.trend == TrendState.TRENDING_UP and close >= latest_vwap:
        side = "BUY"
    elif context.regime.trend == TrendState.TRENDING_DOWN and close <= latest_vwap:
        side = "SELL"
    else:
        return None

    stop, target = atr_stop_and_target(close, latest_atr, side, STOP_MULTIPLE, REWARD_MULTIPLE)
    return StrategySignal(
        strategy=StrategyName.VWAP,
        symbol=context.symbol,
        side=side,
        entry_price=close,
        stop_loss=stop,
        target=target,
        confidence=0.5,
        reason=(
            f"{context.regime.trend.value} regime, close {close:.2f} pulled back to session VWAP "
            f"{latest_vwap:.2f} (within {PULLBACK_ATR_TOLERANCE}x ATR)."
        ),
    )


__all__ = ["generate"]
