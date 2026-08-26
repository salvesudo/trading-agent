"""
Repository layer -- Phase 5.

The only place that translates between ORM rows (app/db/models.py) and
the dataclasses the rest of the codebase already uses and tests
(TradeCandidate/RiskVerdict/AccountState from app/risk/risk_engine.py,
ComplianceReport from app/security/compliance.py, Candle from
app/data/models.py). Nothing outside this module should import
app/db/models.py directly, and nothing in here contains business logic
-- it only persists and reloads what other modules already decided.

Every function takes an explicit `Session` rather than opening its own
-- callers control the transaction boundary (and tests can pass an
in-memory SQLite session without touching a real database).
"""
from __future__ import annotations

import datetime as dt
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.data.models import Candle, Timeframe
from app.db.models import (
    AccountStateRow,
    CandleRow,
    CapitalLedgerRow,
    ComplianceCheckRow,
    PaperTradeRow,
    RiskEvaluationRow,
)
from app.paper.models import ExitReason, PaperPosition, PositionStatus
from app.risk.capital_ledger import CapitalLedger
from app.risk.risk_engine import AccountState, RiskVerdict, TradeCandidate
from app.security.compliance import ComplianceReport


def _as_utc(ts: dt.datetime) -> dt.datetime:
    """SQLite's DateTime(timezone=True) doesn't actually preserve tzinfo
    across a round trip (a real SQLite/SQLAlchemy limitation, unlike
    Postgres which does) -- rows read back from a SQLite-backed session
    come back naive. Every timestamp this repository writes originates
    as UTC-aware (candle_builder.floor_to_bucket, history.fetch_candles),
    so re-attaching UTC to a naive value is always correct, and is a
    no-op for an already-aware value from Postgres."""
    return ts if ts.tzinfo is not None else ts.replace(tzinfo=dt.timezone.utc)


def load_account_state(session: Session, trade_date: Optional[dt.date] = None) -> AccountState:
    """Hydrate app.risk.risk_engine.AccountState from today's row, or
    return the same safe defaults AccountState() already uses when no
    row exists yet (e.g. the first run of a new trading day)."""
    trade_date = trade_date or dt.date.today()
    row = session.scalar(select(AccountStateRow).where(AccountStateRow.trade_date == trade_date))
    if row is None:
        return AccountState()
    return AccountState(
        today_realized_pnl=row.today_realized_pnl,
        consecutive_losses=row.consecutive_losses,
        system_healthy=row.system_healthy,
    )


def save_account_state(
    session: Session, state: AccountState, trade_date: Optional[dt.date] = None
) -> AccountStateRow:
    """Upsert today's AccountState row (one row per trade_date)."""
    trade_date = trade_date or dt.date.today()
    row = session.scalar(select(AccountStateRow).where(AccountStateRow.trade_date == trade_date))
    if row is None:
        row = AccountStateRow(trade_date=trade_date)
        session.add(row)
    row.today_realized_pnl = state.today_realized_pnl
    row.consecutive_losses = state.consecutive_losses
    row.system_healthy = state.system_healthy
    session.flush()
    return row


def load_capital_ledger(session: Session) -> Optional[CapitalLedger]:
    """Hydrate the account's CapitalLedger from its single persisted row.
    Returns None if none exists yet -- unlike load_account_state, there's
    no safe default to fall back to, since the caller (not this module)
    knows what the account's actual starting capital should be
    (app.risk.capital_ledger.initial_ledger reads that from settings)."""
    row = session.scalar(select(CapitalLedgerRow).order_by(CapitalLedgerRow.id.desc()))
    if row is None:
        return None
    return CapitalLedger(
        protected_floor_inr=row.protected_floor_inr,
        tradable_capital_inr=row.tradable_capital_inr,
        reserved_capital_inr=row.reserved_capital_inr,
    )


def save_capital_ledger(session: Session, ledger: CapitalLedger) -> CapitalLedgerRow:
    """Upsert the account's single CapitalLedger row."""
    row = session.scalar(select(CapitalLedgerRow).order_by(CapitalLedgerRow.id.desc()))
    if row is None:
        row = CapitalLedgerRow(protected_floor_inr=ledger.protected_floor_inr)
        session.add(row)
    row.protected_floor_inr = ledger.protected_floor_inr
    row.tradable_capital_inr = ledger.tradable_capital_inr
    row.reserved_capital_inr = ledger.reserved_capital_inr
    session.flush()
    return row


def save_risk_evaluation(session: Session, candidate: TradeCandidate, verdict: RiskVerdict) -> RiskEvaluationRow:
    row = RiskEvaluationRow(
        symbol=candidate.symbol,
        side=candidate.side,
        entry_price=candidate.entry_price,
        stop_loss=candidate.stop_loss,
        target=candidate.target,
        account_equity=candidate.account_equity,
        estimated_costs=candidate.estimated_costs,
        decision=verdict.decision.value,
        approved_quantity=verdict.approved_quantity,
        max_loss_inr=verdict.max_loss_inr,
        risk_pct=verdict.risk_pct,
        reason=verdict.reason,
    )
    session.add(row)
    session.flush()
    return row


def save_compliance_report(session: Session, report: ComplianceReport) -> List[ComplianceCheckRow]:
    rows = [
        ComplianceCheckRow(check_name=check.name, ok=check.ok, detail=check.detail)
        for check in report.checks
    ]
    session.add_all(rows)
    session.flush()
    return rows


def save_candles(session: Session, symbol: str, timeframe: Timeframe, candles: List[Candle]) -> int:
    """Upsert candles: skip any already stored for this symbol/timeframe/
    timestamp rather than erroring on the unique constraint or
    duplicating rows when the same range is seeded more than once."""
    if not candles:
        return 0
    existing_timestamps = {
        _as_utc(ts)
        for ts in session.scalars(
            select(CandleRow.timestamp).where(
                CandleRow.symbol == symbol,
                CandleRow.timeframe == timeframe.value,
                CandleRow.timestamp.in_([c.timestamp for c in candles]),
            )
        )
    }
    new_rows = [
        CandleRow(
            symbol=symbol,
            timeframe=timeframe.value,
            timestamp=c.timestamp,
            open=c.open,
            high=c.high,
            low=c.low,
            close=c.close,
            volume=c.volume,
        )
        for c in candles
        if c.timestamp not in existing_timestamps
    ]
    session.add_all(new_rows)
    session.flush()
    return len(new_rows)


def load_candles(
    session: Session, symbol: str, timeframe: Timeframe, limit: Optional[int] = None
) -> List[Candle]:
    """Return candles in ascending timestamp order. `limit`, if given,
    returns the most recent `limit` candles (still ascending)."""
    base_filter = (CandleRow.symbol == symbol, CandleRow.timeframe == timeframe.value)
    if limit is not None:
        stmt = select(CandleRow).where(*base_filter).order_by(CandleRow.timestamp.desc()).limit(limit)
        rows = list(reversed(session.scalars(stmt).all()))
    else:
        stmt = select(CandleRow).where(*base_filter).order_by(CandleRow.timestamp.asc())
        rows = list(session.scalars(stmt).all())
    return [
        Candle(timestamp=_as_utc(r.timestamp), open=r.open, high=r.high, low=r.low, close=r.close, volume=r.volume)
        for r in rows
    ]


def _paper_position_from_row(row: PaperTradeRow) -> PaperPosition:
    return PaperPosition(
        symbol=row.symbol,
        side=row.side,
        quantity=row.quantity,
        entry_price=row.entry_price,
        stop_loss=row.stop_loss,
        target=row.target,
        opened_at=_as_utc(row.opened_at),
        status=PositionStatus(row.status),
        exit_price=row.exit_price,
        exit_reason=ExitReason(row.exit_reason) if row.exit_reason else None,
        closed_at=_as_utc(row.closed_at) if row.closed_at else None,
        strategy=row.strategy,
        estimated_costs=row.estimated_costs,
    )


def save_new_paper_trade(session: Session, position: PaperPosition) -> PaperTradeRow:
    """Insert a new row for a just-opened position. Raises via a
    UNIQUE-ish app-level check if this symbol already has an OPEN row --
    app/paper/engine.py already prevents this in memory; this is a
    second, independent check at the persistence boundary (defense in
    depth, same pattern used throughout this project)."""
    existing_open = session.scalar(
        select(PaperTradeRow).where(PaperTradeRow.symbol == position.symbol, PaperTradeRow.status == "OPEN")
    )
    if existing_open is not None:
        raise ValueError(f"{position.symbol} already has an OPEN paper trade row (id={existing_open.id}).")
    row = PaperTradeRow(
        symbol=position.symbol,
        side=position.side,
        quantity=position.quantity,
        entry_price=position.entry_price,
        stop_loss=position.stop_loss,
        target=position.target,
        opened_at=position.opened_at,
        status=position.status.value,
        strategy=position.strategy,
        estimated_costs=position.estimated_costs,
    )
    session.add(row)
    session.flush()
    return row


def save_paper_trade_close(session: Session, symbol: str, closed_position: PaperPosition) -> PaperTradeRow:
    """Update the OPEN row for `symbol` to reflect a close. Raises if
    there's no OPEN row to close -- a close with nothing to close
    against is a real inconsistency, not something to silently ignore."""
    if closed_position.status != PositionStatus.CLOSED:
        raise ValueError("save_paper_trade_close expects an already-closed PaperPosition.")
    row = session.scalar(select(PaperTradeRow).where(PaperTradeRow.symbol == symbol, PaperTradeRow.status == "OPEN"))
    if row is None:
        raise ValueError(f"No OPEN paper trade row found for {symbol} to close.")
    row.status = PositionStatus.CLOSED.value
    row.exit_price = closed_position.exit_price
    row.exit_reason = closed_position.exit_reason.value if closed_position.exit_reason else None
    row.closed_at = closed_position.closed_at
    session.flush()
    return row


def load_open_paper_trades(session: Session) -> List[PaperPosition]:
    """All currently OPEN positions -- e.g. to rebuild
    app/paper/engine.py::PaperTradingEngine's in-memory state after a
    restart."""
    rows = session.scalars(select(PaperTradeRow).where(PaperTradeRow.status == "OPEN")).all()
    return [_paper_position_from_row(r) for r in rows]


def load_paper_trade_history(
    session: Session, symbol: Optional[str] = None, limit: Optional[int] = None
) -> List[PaperPosition]:
    """Closed positions, most recently closed first."""
    stmt = select(PaperTradeRow).where(PaperTradeRow.status == "CLOSED")
    if symbol is not None:
        stmt = stmt.where(PaperTradeRow.symbol == symbol)
    stmt = stmt.order_by(PaperTradeRow.closed_at.desc())
    if limit is not None:
        stmt = stmt.limit(limit)
    rows = session.scalars(stmt).all()
    return [_paper_position_from_row(r) for r in rows]


__all__ = [
    "load_account_state",
    "save_account_state",
    "load_capital_ledger",
    "save_capital_ledger",
    "save_risk_evaluation",
    "save_compliance_report",
    "save_candles",
    "load_candles",
    "save_new_paper_trade",
    "save_paper_trade_close",
    "load_open_paper_trades",
    "load_paper_trade_history",
]
