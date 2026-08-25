"""
Strategy engine models -- Phase 9.

A `StrategySignal` is deliberately NOT the same shape as
`app.risk.risk_engine.TradeCandidate` -- a signal only knows about price
levels and the technical/news context that produced it, not the
account's actual equity or this trade's estimated transaction costs.
Assembling those into a TradeCandidate is app/strategy/candidate.py's
job, a separate explicit step (same reason app/broker/models.OrderRequest
is deliberately not the same shape as TradeCandidate either -- see that
module's docstring).

Nothing in app/strategy/ can place an order. A signal is a proposal; the
Risk Engine's decision on the resulting TradeCandidate is final (spec
section 47, docs/PRINCIPLES.md section 1).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List

from app.data.models import Candle
from app.news.models import NewsItem
from app.regime.detector import RegimeSnapshot


class StrategyName(str, Enum):
    TREND_FOLLOWING = "TREND_FOLLOWING"
    MOMENTUM = "MOMENTUM"
    MEAN_REVERSION = "MEAN_REVERSION"
    BREAKOUT = "BREAKOUT"
    VWAP = "VWAP"
    NEWS = "NEWS"


@dataclass(frozen=True)
class StrategySignal:
    strategy: StrategyName
    symbol: str
    side: str  # "BUY" | "SELL", matches app.risk.risk_engine.TradeCandidate
    entry_price: float
    stop_loss: float
    target: float
    confidence: float  # 0.0-1.0, this strategy's own rough conviction -- not a calibrated probability
    reason: str


@dataclass(frozen=True)
class StrategyContext:
    """Everything a strategy function needs, assembled by the caller.
    Strategies are pure functions of this -- no network calls, no
    broker/DB access, so every strategy in app/strategy/ is fully
    unit-testable without mocking anything beyond this object."""

    symbol: str
    candles: List[Candle]  # ascending order, most recent last
    regime: RegimeSnapshot
    news_items: List[NewsItem] = field(default_factory=list)  # pre-filtered to this symbol


__all__ = ["StrategyName", "StrategySignal", "StrategyContext"]
