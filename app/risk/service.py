"""
Risk service -- Phase 10.

The Phase-1 Risk Engine and Phase-9 Capital Ledger are both pure logic
with no DB dependency, tested in isolation. Phase 5 built the schema to
persist them. This module is the missing piece tying all three
together into the operations a caller actually needs:

  - load today's real AccountState and a ready-to-use RiskEngine from
    the database instead of Phase-1's in-memory placeholder defaults
  - load (or lazily create) the account's one CapitalLedger
  - close a trade: update AccountState (today's P&L, consecutive-loss
    streak) AND CapitalLedger (the 20%-of-profit sweep) together,
    atomically in one session, so the two can never drift out of sync
    with each other

Still not wired into a live loop -- this is the service layer Phase 11
(paper trading engine) is expected to call once it exists, not a loop
itself (docs/PRINCIPLES.md section 15). Nothing here changes what the
Risk Engine or Capital Ledger actually decide; it only gives them
somewhere real to read from and write to.
"""
from __future__ import annotations

import datetime as dt
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app.db import repository
from app.risk.capital_ledger import CapitalLedger, initial_ledger
from app.risk.risk_engine import AccountState, RiskEngine


def load_account_state(session: Session, trade_date: Optional[dt.date] = None) -> AccountState:
    """Thin wrapper over app.db.repository.load_account_state -- exists
    so callers only need to import this one module for the whole
    "risk + capital, backed by the database" surface."""
    return repository.load_account_state(session, trade_date=trade_date)


def load_or_initialize_ledger(session: Session) -> CapitalLedger:
    """Load the persisted CapitalLedger, or create and persist a fresh
    one (from settings' INITIAL_CAPITAL_INR / PROTECTED_CAPITAL_INR) if
    this is the very first time this has been called for the account.
    After this, there is always exactly one ledger to load."""
    ledger = repository.load_capital_ledger(session)
    if ledger is None:
        ledger = initial_ledger()
        repository.save_capital_ledger(session, ledger)
    return ledger


def build_risk_engine(session: Session, trade_date: Optional[dt.date] = None) -> RiskEngine:
    """A RiskEngine constructed from today's real, DB-backed
    AccountState -- what app/agent.py's Phase-1 default construction
    (`RiskEngine()`, implicitly `AccountState()`) should be replaced
    with once a caller has a real database session available."""
    return RiskEngine(load_account_state(session, trade_date=trade_date))


def compute_next_account_state(current: AccountState, realized_pnl: float) -> AccountState:
    """Pure: what AccountState should become after one more trade closes,
    given its realized P&L. No session, no side effects.

    - today_realized_pnl accumulates every trade's P&L.
    - consecutive_losses increments on a loss, resets to 0 on a win, and
      is left unchanged on an exact breakeven (0.0) -- a scratch trade
      neither extends nor breaks a losing streak.

    Used by both record_trade_close (DB-backed) and app/backtest/engine.py
    (in-memory, no DB) so the same rule applies in both places rather
    than being duplicated and risking drift between them.
    """
    if realized_pnl < 0:
        new_consecutive_losses = current.consecutive_losses + 1
    elif realized_pnl > 0:
        new_consecutive_losses = 0
    else:
        new_consecutive_losses = current.consecutive_losses
    return AccountState(
        today_realized_pnl=current.today_realized_pnl + realized_pnl,
        consecutive_losses=new_consecutive_losses,
        system_healthy=current.system_healthy,
    )


def record_trade_close(
    session: Session,
    realized_pnl: float,
    trade_date: Optional[dt.date] = None,
) -> Tuple[AccountState, CapitalLedger]:
    """Record one closed trade's outcome against both the day's
    AccountState and the account's CapitalLedger, and persist both in
    this same session (the caller controls the commit boundary, same
    convention as every other repository function).

    - AccountState: see compute_next_account_state.
    - CapitalLedger splits a profit 80/20 (tradable/reserved) per
      PROFIT_RESERVE_PCT; a loss comes entirely out of tradable capital
      (see app/risk/capital_ledger.py).
    """
    trade_date = trade_date or dt.date.today()

    state = load_account_state(session, trade_date=trade_date)
    updated_state = compute_next_account_state(state, realized_pnl)
    repository.save_account_state(session, updated_state, trade_date=trade_date)

    ledger = load_or_initialize_ledger(session)
    updated_ledger = ledger.apply_trade_outcome(realized_pnl)
    repository.save_capital_ledger(session, updated_ledger)

    return updated_state, updated_ledger


__all__ = [
    "load_account_state",
    "load_or_initialize_ledger",
    "build_risk_engine",
    "compute_next_account_state",
    "record_trade_close",
]
