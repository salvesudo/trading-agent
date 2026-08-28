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
1.5R - 0.6 * 1R = 0), just asks for a more realistic move.

MAX_BARS_SINCE_FLIP added the same day, closing the "entries may be
catching trends too late" question left open above. Third round of
real-data backtests (after the REWARD_MULTIPLE fix) showed a real
improvement -- 0% win rate became 35.3% -- but still net negative,
because `st.direction[-1] == 1` alone allows entry on *any* bar during
an already-long-running uptrend, not just near where it started: three
lagging confirmations (ADX crossing its regime threshold, price
already above EMA20, Supertrend already flipped) stacked together can
mean the easy part of a move is over by the time all three agree.
Supertrend itself already IS a trend-start signal (it flips right when
price crosses its band) -- the fix isn't to drop it, it's to stop
accepting it long after the fact. MAX_BARS_SINCE_FLIP bounds how stale
the flip may be; the regime/EMA gates are untouched (still required,
so this only makes entry *stricter* on timing, not looser on
confirmation).

MAX_BARS_SINCE_FLIP=15, not something tighter: tested against
synthetic breakouts of several speeds (weak/moderate/strong step
sizes) after a ranging warm-up, ADX(14) consistently takes 8-10 bars
*after* the Supertrend flip to itself cross the regime's 25 threshold,
regardless of trend strength -- ADX's own 14-period smoothing lags a
fresh flip by roughly that much no matter how fast the move is. An
initial attempt at 5 bars was tested and rejected for exactly this
reason: it made the strategy structurally unable to ever fire in any
of those scenarios, since by the time the regime gate opened, the
flip was already always 8+ bars stale. 15 leaves real margin above
that observed 8-10 bar lag while still being far tighter than the
unbounded staleness this replaces. See docs/PRINCIPLES.md section 25.
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
MAX_BARS_SINCE_FLIP = 15  # was unbounded -- see module docstring, 2026-08-28


def _bars_since_last_flip(direction: list) -> int:
    """How many bars ago the Supertrend direction most recently
    changed. 0 means the flip is on the very last bar (freshest
    possible); returns len(direction) - 1 if there's no flip anywhere
    in the given history (direction has been constant throughout what
    we can see)."""
    current = direction[-1]
    for i in range(len(direction) - 1, 0, -1):
        if direction[i - 1] != current:
            return (len(direction) - 1) - i
    return len(direction) - 1


def generate(context: StrategyContext) -> Optional[StrategySignal]:
    if context.regime.trend == TrendState.RANGING:
        return None
    try:
        ema_values = indicators.ema(context.candles, window=EMA_WINDOW)
        atr_values = indicators.atr(context.candles, window=ATR_WINDOW)
        st = indicators.supertrend(context.candles)
    except InsufficientDataError:
        return None

    bars_since_flip = _bars_since_last_flip(st.direction)
    if bars_since_flip > MAX_BARS_SINCE_FLIP:
        return None  # trend's already been running a while -- too late to call this "catching" it

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
            f"EMA{EMA_WINDOW}={latest_ema:.2f}, Supertrend direction={st.direction[-1]} "
            f"(flipped {bars_since_flip} bar(s) ago), ADX={context.regime.adx:.1f}."
        ),
    )


__all__ = ["generate"]
