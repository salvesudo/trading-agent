"""
Paper trading service -- Phase 11.

Ties app/paper/engine.py (in-memory position lifecycle),
app/db/repository.py (persistence), and app/risk/service.py (DB-backed
AccountState + CapitalLedger, Phase 10) together into the two
operations a caller actually needs: open a position (persisted
immediately) and close one (persisted AND booked against
AccountState/CapitalLedger, atomically, in one session) -- so a closed
paper trade can never exist in the position ledger without also being
reflected in the account's P&L and capital reserve, or vice versa.

Not wired into a live loop yet -- same status as everything this phase's
pieces depend on (docs/PRINCIPLES.md sections 15, 21). This is the
service layer a future scheduler is expected to call, not a loop itself.
"""
from __future__ import annotations

import datetime as dt
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.db import repository
from app.paper.engine import PaperTradingEngine
from app.paper.models import PaperPosition
from app.risk import service as risk_service
from app.risk.risk_engine import RiskVerdict, TradeCandidate

IST = ZoneInfo("Asia/Kolkata")


def _trade_date_from(current_time: dt.datetime) -> dt.date:
    """The IST calendar date `current_time` falls on -- NOT
    `dt.date.today()`. Defaulting to the real-world "today" here would
    silently misattribute a closed trade's P&L to the wrong AccountState
    row whenever `current_time` is a backtested/simulated timestamp
    rather than the actual current moment (caught by this module's own
    tests -- see git history)."""
    return current_time.astimezone(IST).date()


def open_position(
    session: Session,
    engine: PaperTradingEngine,
    candidate: TradeCandidate,
    verdict: RiskVerdict,
    opened_at: dt.datetime,
) -> PaperPosition:
    """Open a position in the engine and persist it in the same call --
    an open position that exists in memory but not in the database (or
    vice versa) is exactly the inconsistency this module exists to
    prevent."""
    position = engine.open_position(candidate, verdict, opened_at)
    repository.save_new_paper_trade(session, position)
    return position


def close_position(
    session: Session,
    engine: PaperTradingEngine,
    symbol: str,
    price: float,
    current_time: dt.datetime,
    trade_date: Optional[dt.date] = None,
) -> Optional[PaperPosition]:
    """Check `symbol` for an exit (stop/target/square-off) and, if one
    occurred, persist the close AND book its realized P&L against
    AccountState/CapitalLedger (app/risk/service.py::record_trade_close)
    in this same session. Returns None if the position stayed open --
    nothing to book yet."""
    closed = engine.process_price_update(symbol, price, current_time)
    if closed is None:
        return None
    repository.save_paper_trade_close(session, symbol, closed)
    risk_service.record_trade_close(
        session, closed.realized_pnl(), trade_date=trade_date or _trade_date_from(current_time)
    )
    return closed


def close_position_manually(
    session: Session,
    engine: PaperTradingEngine,
    symbol: str,
    price: float,
    current_time: dt.datetime,
    trade_date: Optional[dt.date] = None,
) -> PaperPosition:
    """Same as close_position, but always forces a close (e.g. the kill
    switch flips mid-day and every open position must be flattened
    immediately -- docs/PRINCIPLES.md section 8) rather than only
    closing on a stop/target/square-off condition."""
    closed = engine.close_manually(symbol, price, current_time)
    repository.save_paper_trade_close(session, symbol, closed)
    risk_service.record_trade_close(
        session, closed.realized_pnl(), trade_date=trade_date or _trade_date_from(current_time)
    )
    return closed


def restore_open_positions(session: Session, engine: PaperTradingEngine) -> int:
    """Rebuild the engine's in-memory open positions from the database
    -- e.g. after a process restart. Returns how many were restored.
    Meant for a freshly-constructed engine; restoring into one that
    already tracks a symbol will raise via
    PaperTradingEngine.restore_position's own duplicate-symbol guard."""
    restored = 0
    for position in repository.load_open_paper_trades(session):
        engine.restore_position(position)
        restored += 1
    return restored


__all__ = ["open_position", "close_position", "close_position_manually", "restore_open_positions"]
