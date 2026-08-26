"""
Paper trading models -- Phase 11.

A `PaperPosition` is a simulated fill: never a real broker order (see
app/broker/client.py's own TRADING_MODE=LIVE guard, which this never
touches). It exists purely to give the Risk Engine's approvals
somewhere to live and be tracked to a close, so "today's realized P&L"
(app/risk/risk_engine.py's AccountState) and the profit reserve
(app/risk/capital_ledger.py) have real numbers to work from.

`strategy` (added in Phase 12) is deliberately a plain string, not an
imported `app.strategy.models.StrategyName` -- same reason `side` is a
plain str rather than an imported broker enum: this module stays
decoupled from what produced a position, it only tracks the position
itself. It exists so a backtest (app/backtest/engine.py) can attribute
results per strategy; it's optional and defaults to None everywhere
else, so nothing that predates Phase 12 needs to change.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class PositionStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ExitReason(str, Enum):
    STOP_LOSS = "STOP_LOSS"
    TARGET = "TARGET"
    EOD_SQUARE_OFF = "EOD_SQUARE_OFF"
    MANUAL = "MANUAL"


@dataclass(frozen=True)
class PaperPosition:
    symbol: str
    side: str  # "BUY" | "SELL", matches app.risk.risk_engine.TradeCandidate
    quantity: int
    entry_price: float
    stop_loss: float
    target: float
    opened_at: dt.datetime
    status: PositionStatus = PositionStatus.OPEN
    exit_price: Optional[float] = None
    exit_reason: Optional[ExitReason] = None
    closed_at: Optional[dt.datetime] = None
    strategy: Optional[str] = None  # e.g. "TREND_FOLLOWING" -- see module docstring
    estimated_costs: float = 0.0  # from TradeCandidate.estimated_costs -- see realized_pnl()

    @property
    def is_open(self) -> bool:
        return self.status == PositionStatus.OPEN

    def _direction(self) -> int:
        return 1 if self.side == "BUY" else -1

    def unrealized_pnl(self, current_price: float) -> float:
        """Mark-to-market P&L at `current_price`, ignoring costs --
        for monitoring an open position, not for booking a close."""
        return (current_price - self.entry_price) * self._direction() * self.quantity

    def close(self, exit_price: float, reason: ExitReason, closed_at: dt.datetime) -> "PaperPosition":
        """Return a new, closed PaperPosition. Frozen/functional style,
        same convention as app.risk.capital_ledger.CapitalLedger --
        the original instance is never mutated."""
        if not self.is_open:
            raise ValueError(f"Position on {self.symbol} is already {self.status.value}.")
        return PaperPosition(
            symbol=self.symbol, side=self.side, quantity=self.quantity,
            entry_price=self.entry_price, stop_loss=self.stop_loss, target=self.target,
            opened_at=self.opened_at, status=PositionStatus.CLOSED,
            exit_price=exit_price, exit_reason=reason, closed_at=closed_at,
            strategy=self.strategy, estimated_costs=self.estimated_costs,
        )

    def gross_pnl(self) -> float:
        """Pure price P&L, ignoring costs entirely -- exists only so
        callers that specifically want the pre-cost number can get it.
        realized_pnl() below is what the ledger/risk engine actually use."""
        if self.status != PositionStatus.CLOSED or self.exit_price is None:
            raise ValueError(f"Position on {self.symbol} is still OPEN -- nothing realized yet.")
        return (self.exit_price - self.entry_price) * self._direction() * self.quantity

    def realized_pnl(self) -> float:
        """P&L booked at close, net of `estimated_costs`. Costs default
        to 0.0 for backward compatibility (any position built before
        this field existed, or in a test that doesn't set it, behaves
        exactly as before). This used to ignore costs entirely on the
        theory that "the Risk Engine already accounted for them when
        sizing" -- true for *approval*, but the money was never actually
        deducted anywhere: the capital ledger, today's realized P&L, and
        every backtest report were all silently gross-of-costs. Fixed
        because that's the number that drives real safety checks
        (daily loss limit, protected floor) -- understating how much a
        losing day actually cost is exactly the kind of optimism this
        project is built to avoid (docs/PRINCIPLES.md section 1)."""
        return self.gross_pnl() - self.estimated_costs


__all__ = ["PositionStatus", "ExitReason", "PaperPosition"]
