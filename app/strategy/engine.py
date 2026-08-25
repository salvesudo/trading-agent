"""
Strategy engine -- Phase 9.

Runs every registered strategy (trend/momentum/mean-reversion/breakout/
vwap/news) against one StrategyContext and collects whatever signals
they propose. This module does not decide which signal "wins" beyond
the simple confidence-based tiebreak in select_best_signal -- real
arbitration across competing strategies (weighting by regime fit,
historical performance, etc.) is later-phase work, likely Phase 13's AI
decision layer, which is advisory only and still cannot override the
Risk Engine (spec section 47, docs/PRINCIPLES.md section 1).

A strategy raising InsufficientDataError (too few candles for one of
its own indicators) is treated as "no signal from that strategy right
now," not an error -- one strategy lacking enough history shouldn't
block every other strategy from running. Each strategy module already
catches this internally too (defense in depth, same pattern used
throughout this project); this is a backstop, not the only guard.
"""
from __future__ import annotations

from typing import Callable, List, Optional

from app.analysis.indicators import InsufficientDataError
from app.strategy import breakout, mean_reversion, momentum, news, trend, vwap
from app.strategy.models import StrategyContext, StrategySignal

Strategy = Callable[[StrategyContext], Optional[StrategySignal]]

DEFAULT_STRATEGIES: List[Strategy] = [
    trend.generate,
    momentum.generate,
    mean_reversion.generate,
    breakout.generate,
    vwap.generate,
    news.generate,
]


def generate_signals(
    context: StrategyContext, strategies: Optional[List[Strategy]] = None
) -> List[StrategySignal]:
    signals: List[StrategySignal] = []
    for strategy in strategies or DEFAULT_STRATEGIES:
        try:
            signal = strategy(context)
        except InsufficientDataError:
            continue
        if signal is not None:
            signals.append(signal)
    return signals


def select_best_signal(signals: List[StrategySignal]) -> Optional[StrategySignal]:
    """Simple placeholder arbitration: highest confidence wins, ties
    broken by whichever came first in `signals`. Not a claim this is the
    right way to arbitrate between disagreeing strategies -- see this
    module's own docstring."""
    if not signals:
        return None
    return max(signals, key=lambda s: s.confidence)


__all__ = ["Strategy", "DEFAULT_STRATEGIES", "generate_signals", "select_best_signal"]
