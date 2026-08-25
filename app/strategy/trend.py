"""
Trend-following strategy -- Phase 9.

Simple, explicit rule, not the product of any backtesting or
optimization (see docs/PRINCIPLES.md on unvalidated thresholds): trade
in the direction of app.regime.detector's classified trend, confirmed
by price being on the "right side" of both the 20-period EMA and the
Supertrend line. No entry while the regime is RANGING -- that's
mean_reversion.py's job, not this strategy's, and the two are meant to
disagree by design rather than both firing on the same bar.
"""
from __future__ import annotations

from typing import Optional

from app.analysis import indicators
from app.analysis.indicators import InsufficientDataError
from app.regime.detector import TrendState
from app.strategy.models import StrategyContext, StrategyName, StrategySignal
from app.strategy.sizing import atr_stop_and_target

EMA_WINDOW = 20
ATR_WINDOW = 14
STOP_MULTIPLE = 1.5
REWARD_MULTIPLE = 2.0


def generate(context: StrategyContext) -> Optional[StrategySignal]:
    if context.regime.trend == TrendState.RANGING:
        return None
    try:
        ema_values = indicators.ema(context.candles, window=EMA_WINDOW)
        atr_values = indicators.atr(context.candles, window=ATR_WINDOW)
        st = indicators.supertrend(context.candles)
    except InsufficientDataError:
        return None

    close = context.candles[-1].close
    latest_ema = ema_values[-1]
    latest_atr = atr_values[-1]

    if context.regime.trend == TrendState.TRENDING_UP:
        if not (close > latest_ema and st.direction[-1] == 1):
            return None
        side = "BUY"
    else:  # TRENDING_DOWN
        if not (close < latest_ema and st.direction[-1] == -1):
            return None
        side = "SELL"

    stop, target = atr_stop_and_target(close, latest_atr, side, STOP_MULTIPLE, REWARD_MULTIPLE)
    return StrategySignal(
        strategy=StrategyName.TREND_FOLLOWING,
        symbol=context.symbol,
        side=side,
        entry_price=close,
        stop_loss=stop,
        target=target,
        confidence=min(1.0, context.regime.adx / 50.0),  # stronger trend -> higher confidence, capped at 1.0
        reason=(
            f"Regime={context.regime.trend.value}, close {'>' if side == 'BUY' else '<'} "
            f"EMA{EMA_WINDOW}={latest_ema:.2f}, Supertrend direction={st.direction[-1]}, "
            f"ADX={context.regime.adx:.1f}."
        ),
    )


__all__ = ["generate"]
