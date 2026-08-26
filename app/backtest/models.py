"""
Backtest result models -- Phase 12.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import List

from app.paper.models import PaperPosition


@dataclass(frozen=True)
class StrategyStats:
    strategy: str  # "UNKNOWN" if a position carries no strategy attribution
    trade_count: int
    wins: int
    losses: int
    total_pnl_inr: float

    @property
    def win_rate_pct(self) -> float:
        return (self.wins / self.trade_count * 100.0) if self.trade_count else 0.0


@dataclass(frozen=True)
class BacktestResult:
    symbol: str
    start: dt.datetime
    end: dt.datetime
    starting_capital_inr: float
    ending_tradable_capital_inr: float
    ending_reserved_capital_inr: float
    total_trades: int
    wins: int
    losses: int
    total_realized_pnl_inr: float
    max_drawdown_pct: float
    per_strategy: List[StrategyStats] = field(default_factory=list)
    trades: List[PaperPosition] = field(default_factory=list)

    @property
    def ending_total_equity_inr(self) -> float:
        return self.ending_tradable_capital_inr + self.ending_reserved_capital_inr

    @property
    def win_rate_pct(self) -> float:
        return (self.wins / self.total_trades * 100.0) if self.total_trades else 0.0

    @property
    def net_return_pct(self) -> float:
        if self.starting_capital_inr == 0:
            return 0.0
        return (self.ending_total_equity_inr - self.starting_capital_inr) / self.starting_capital_inr * 100.0

    @property
    def total_estimated_costs_inr(self) -> float:
        """Sum of every closed trade's own `estimated_costs` -- purely
        informational (total_realized_pnl_inr already nets this out via
        PaperPosition.realized_pnl(); this just shows how much of the
        story costs are)."""
        return sum(t.estimated_costs for t in self.trades)


__all__ = ["StrategyStats", "BacktestResult"]
