"""
ORM models -- Phase 5.

These map onto the dataclasses that already exist and are already
tested elsewhere: app/risk/risk_engine.py's TradeCandidate/RiskVerdict/
AccountState, app/security/compliance.py's CheckResult, app/data/models.py's
Candle. This module only defines storage shape; app/db/repository.py is
the only place that should translate between ORM rows and those
dataclasses -- nothing else in the codebase should import these row
classes directly.
"""
from __future__ import annotations

import datetime as dt
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class AccountStateRow(Base):
    """One row per trading day. Hydrates app.risk.risk_engine.AccountState
    -- see app/db/repository.py::load_account_state. Not wired into the
    live agent loop automatically yet (see docs/PRINCIPLES.md) -- that's
    Phase 11 (paper trading engine), once there's an actual persistent
    trading loop for "today's realized P&L" to mean something across."""

    __tablename__ = "account_state"
    __table_args__ = (UniqueConstraint("trade_date", name="uq_account_state_trade_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    trade_date: Mapped[dt.date] = mapped_column(Date, nullable=False, index=True)
    today_realized_pnl: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    consecutive_losses: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    system_healthy: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )


class CapitalLedgerRow(Base):
    """Persisted app.risk.capital_ledger.CapitalLedger -- the
    owner-directed profit-reserve policy added after Phase 9. Single row
    per account (there's only ever one live ledger, unlike
    AccountStateRow which is one-per-day) -- see
    app/db/repository.py::load_capital_ledger / save_capital_ledger."""

    __tablename__ = "capital_ledger"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    protected_floor_inr: Mapped[float] = mapped_column(Float, nullable=False)
    tradable_capital_inr: Mapped[float] = mapped_column(Float, nullable=False)
    reserved_capital_inr: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )


class RiskEvaluationRow(Base):
    """Audit log of every Risk Engine evaluation, approved or rejected.
    Written regardless of outcome -- a rejection is as important to have
    on record as an approval (spec section 47: the Risk Engine's decision
    is final, and that only means something if it's auditable)."""

    __tablename__ = "risk_evaluations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, index=True
    )
    symbol: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    stop_loss: Mapped[float] = mapped_column(Float, nullable=False)
    target: Mapped[float] = mapped_column(Float, nullable=False)
    account_equity: Mapped[float] = mapped_column(Float, nullable=False)
    estimated_costs: Mapped[float] = mapped_column(Float, nullable=False)
    decision: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    approved_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    max_loss_inr: Mapped[float] = mapped_column(Float, nullable=False)
    risk_pct: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)


class ComplianceCheckRow(Base):
    """One row per individual check per compliance_check.py run (see
    app/security/compliance.py's CheckResult)."""

    __tablename__ = "compliance_checks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, index=True
    )
    check_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    detail: Mapped[str] = mapped_column(String(1000), nullable=False)


class CandleRow(Base):
    """Persisted OHLCV candles (see app/data/models.Candle), so market
    data survives a restart instead of living only in
    app/data/store.py's in-memory, bounded MarketDataStore."""

    __tablename__ = "candles"
    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", "timestamp", name="uq_candle_symbol_timeframe_ts"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False, index=True)
    timestamp: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[int] = mapped_column(Integer, nullable=False)


class PaperTradeRow(Base):
    """Persisted app.paper.models.PaperPosition -- Phase 11. One row per
    position's entire lifetime, updated in place from OPEN to CLOSED
    (not append-only) -- matches how app/paper/engine.py enforces at
    most one open position per symbol at a time. See
    app/db/repository.py::save_new_paper_trade / save_paper_trade_close."""

    __tablename__ = "paper_trades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    entry_price: Mapped[float] = mapped_column(Float, nullable=False)
    stop_loss: Mapped[float] = mapped_column(Float, nullable=False)
    target: Mapped[float] = mapped_column(Float, nullable=False)
    opened_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(8), nullable=False, default="OPEN", index=True)
    exit_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    exit_reason: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    closed_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    strategy: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)  # Phase 12: per-strategy attribution


__all__ = [
    "AccountStateRow",
    "CapitalLedgerRow",
    "RiskEvaluationRow",
    "ComplianceCheckRow",
    "CandleRow",
    "PaperTradeRow",
]
