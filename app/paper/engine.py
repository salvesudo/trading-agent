"""
Paper trading engine -- Phase 11.

A pure, in-memory position-lifecycle state machine: feed it price
updates and it tells you when a position closed (stop hit, target hit,
or the intraday square-off time passed). It does not decide what to
open -- that's the Strategy Engine (Phase 9) + Risk Engine (Phase
1/10)'s job; this only tracks an already-approved position through to
a close. It never touches the broker (app/broker/client.py, which
carries its own independent TRADING_MODE=LIVE guard) or the database --
app/paper/service.py is where persistence and the Risk Engine's
DB-backed AccountState/CapitalLedger (Phase 10) actually get updated
once a position closes.

Enforces the one portfolio-level exposure control the Risk Engine has
no way to see on its own: `MAX_CONCURRENT_POSITIONS` (it only ever
evaluates one candidate in isolation) and one open position per symbol
at a time.

Exit price is always whatever price was observed when the exit
condition was detected, never the idealized stop/target level -- this
doesn't model slippage beyond that, and deliberately doesn't pretend a
real fill lands exactly on the nominal price in a fast-moving market.
"""
from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.paper.models import ExitReason, PaperPosition
from app.risk.risk_engine import RiskDecision, RiskVerdict, TradeCandidate

IST = ZoneInfo("Asia/Kolkata")


class PositionLimitError(RuntimeError):
    """Raised when opening a position would breach MAX_CONCURRENT_POSITIONS
    or duplicate an already-open symbol. An approved trade that can't
    actually be opened is a real event a caller needs to see, not
    something to swallow silently."""


class PaperTradingEngine:
    def __init__(self) -> None:
        self._open: Dict[str, PaperPosition] = {}
        self.closed: List[PaperPosition] = []

    @property
    def open_positions(self) -> List[PaperPosition]:
        return list(self._open.values())

    def open_position(
        self, candidate: TradeCandidate, verdict: RiskVerdict, opened_at: dt.datetime
    ) -> PaperPosition:
        """Open a simulated fill for an APPROVED candidate."""
        if verdict.decision != RiskDecision.APPROVE:
            raise ValueError(
                f"Cannot open a position from a non-approved verdict ({verdict.decision.value})."
            )
        if candidate.symbol in self._open:
            raise PositionLimitError(f"{candidate.symbol} already has an open position.")
        if len(self._open) >= settings.max_concurrent_positions:
            raise PositionLimitError(
                f"MAX_CONCURRENT_POSITIONS ({settings.max_concurrent_positions}) reached."
            )
        position = PaperPosition(
            symbol=candidate.symbol,
            side=candidate.side,
            quantity=verdict.approved_quantity,
            entry_price=candidate.entry_price,
            stop_loss=candidate.stop_loss,
            target=candidate.target,
            opened_at=opened_at,
        )
        self._open[candidate.symbol] = position
        return position

    def _is_past_square_off(self, current_time: dt.datetime) -> bool:
        hour_str, minute_str = settings.intraday_square_off_time.split(":")
        square_off = (int(hour_str), int(minute_str))
        local_time = current_time.astimezone(IST)
        return (local_time.hour, local_time.minute) >= square_off

    def process_price_update(
        self, symbol: str, price: float, current_time: dt.datetime
    ) -> Optional[PaperPosition]:
        """Check the open position on `symbol` (if any) against `price`
        and `current_time`. Closes and returns it if the stop, target,
        or the intraday square-off time has been reached -- checked in
        that order, though stop and target are mutually exclusive by
        construction (they sit on opposite sides of entry for any
        Risk-Engine-approved candidate). Returns None if there's no
        open position on this symbol, or it stays open.
        """
        position = self._open.get(symbol)
        if position is None:
            return None

        hit_stop = price <= position.stop_loss if position.side == "BUY" else price >= position.stop_loss
        hit_target = price >= position.target if position.side == "BUY" else price <= position.target

        if hit_stop:
            closed = position.close(price, ExitReason.STOP_LOSS, current_time)
        elif hit_target:
            closed = position.close(price, ExitReason.TARGET, current_time)
        elif self._is_past_square_off(current_time):
            closed = position.close(price, ExitReason.EOD_SQUARE_OFF, current_time)
        else:
            return None

        del self._open[symbol]
        self.closed.append(closed)
        return closed

    def restore_position(self, position: PaperPosition) -> None:
        """Seed an already-open position into the engine directly --
        e.g. rebuilding state from app/paper/service.py::restore_open_positions
        after a process restart. Unlike open_position(), this doesn't
        take a TradeCandidate/RiskVerdict (there's no new approval
        happening, just resuming tracking of one that already
        happened), but still enforces the same duplicate-symbol and
        concurrency-cap invariants as a normal open."""
        if not position.is_open:
            raise ValueError(f"Cannot restore {position.symbol}: position is not OPEN.")
        if position.symbol in self._open:
            raise PositionLimitError(f"{position.symbol} already has an open position.")
        if len(self._open) >= settings.max_concurrent_positions:
            raise PositionLimitError(
                f"MAX_CONCURRENT_POSITIONS ({settings.max_concurrent_positions}) reached."
            )
        self._open[position.symbol] = position

    def close_manually(self, symbol: str, price: float, current_time: dt.datetime) -> PaperPosition:
        """Force-close an open position regardless of stop/target/square-off
        -- e.g. STOP_TRADING flips mid-day and every open position must
        be flattened immediately (docs/PRINCIPLES.md section 8)."""
        position = self._open.get(symbol)
        if position is None:
            raise KeyError(f"No open position on {symbol}.")
        closed = position.close(price, ExitReason.MANUAL, current_time)
        del self._open[symbol]
        self.closed.append(closed)
        return closed


__all__ = ["PaperTradingEngine", "PositionLimitError"]
