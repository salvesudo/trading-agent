"""
Trend-following strategy -- Phase 9.

Simple, explicit rule, not the product of any backtesting or
optimization (see docs/PRINCIPLES.md on unvalidated thresholds): trade
in the direction of app.regime.detector's classified trend, confirmed
by price being on the "right side" of both the 20-period EMA and the
Supertrend line. No entry while the regime is RANGING -- that's
mean_reversion.py's job, not this strategy's, and the two are meant to
disagree by design rather than both firing on the same bar.

REWARD_MULTIPLE was 2.0 until 2026-08-28: across the first two rounds
of real-data backtests (RELIANCE, INFY, ICICIBANK, TCS), this strategy
went 0-for-10 -- never once reached target. One trade (TCS) held a
full trading day, the maximum possible runway before square-off, and
still only covered ~24% of the distance to a 2x target. Lowered to 1.5
as a direct, evidence-backed correction, not a fit to this specific
sample: still keeps positive expectancy above a 40% win rate (0.4 *
1.5R - 0.6 * 1R = 0), just asks for a more realistic move. The
"entries may be catching trends too late" question (confirmation
requires ADX regime + EMA + Supertrend to already agree, which can lag
a fresh trend by several bars) is still open -- see
docs/PRINCIPLES.md section 24.
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
REWARD_MULTIPLE = 1.5  # was 2.0 -- see module docstring, 2026-08-28


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
