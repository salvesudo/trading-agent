import os

os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost/test")

import datetime as dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.base import Base
from app.risk import service
from app.risk.risk_engine import AccountState, RiskDecision, TradeCandidate


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    with Session(engine, future=True, expire_on_commit=False) as s:
        yield s


def test_load_account_state_defaults_when_nothing_saved(session):
    assert service.load_account_state(session, trade_date=dt.date(2026, 1, 1)) == AccountState()


def test_load_or_initialize_ledger_creates_and_persists_a_fresh_one(session):
    ledger = service.load_or_initialize_ledger(session)
    assert ledger.tradable_capital_inr == settings.initial_capital_inr
    assert ledger.protected_floor_inr == settings.protected_capital_inr
    assert ledger.reserved_capital_inr == 0.0

    # A second call must return the SAME ledger, not create another one.
    again = service.load_or_initialize_ledger(session)
    assert again == ledger


def test_build_risk_engine_reflects_persisted_consecutive_losses(session):
    from app.db import repository

    repository.save_account_state(
        session, AccountState(consecutive_losses=settings.consecutive_loss_hard_limit), trade_date=dt.date.today()
    )
    engine = service.build_risk_engine(session)

    candidate = TradeCandidate(
        symbol="RELIANCE", side="BUY", entry_price=2500.0, stop_loss=2480.0,
        target=2560.0, account_equity=5000.0, estimated_costs=15.0,
    )
    verdict = engine.evaluate(candidate)
    assert verdict.decision == RiskDecision.REJECT_CONSECUTIVE_LOSSES


def test_record_trade_close_on_a_win_resets_streak_and_updates_ledger(session):
    from app.db import repository

    repository.save_account_state(session, AccountState(consecutive_losses=3), trade_date=dt.date.today())

    state, ledger = service.record_trade_close(session, realized_pnl=100.0)

    assert state.today_realized_pnl == pytest.approx(100.0)
    assert state.consecutive_losses == 0
    assert ledger.reserved_capital_inr == pytest.approx(20.0)  # 20% of 100
    assert ledger.tradable_capital_inr == pytest.approx(settings.initial_capital_inr + 80.0)


def test_record_trade_close_on_a_loss_increments_streak_and_hits_tradable_only(session):
    state, ledger = service.record_trade_close(session, realized_pnl=-50.0)

    assert state.today_realized_pnl == pytest.approx(-50.0)
    assert state.consecutive_losses == 1
    assert ledger.reserved_capital_inr == 0.0
    assert ledger.tradable_capital_inr == pytest.approx(settings.initial_capital_inr - 50.0)


def test_record_trade_close_on_exact_breakeven_leaves_streak_unchanged(session):
    from app.db import repository

    repository.save_account_state(session, AccountState(consecutive_losses=2), trade_date=dt.date.today())
    state, _ = service.record_trade_close(session, realized_pnl=0.0)
    assert state.consecutive_losses == 2


def test_record_trade_close_persists_across_separate_loads(session):
    service.record_trade_close(session, realized_pnl=100.0)
    session.commit()

    reloaded_state = service.load_account_state(session)
    reloaded_ledger = service.load_or_initialize_ledger(session)
    assert reloaded_state.today_realized_pnl == pytest.approx(100.0)
    assert reloaded_ledger.reserved_capital_inr == pytest.approx(20.0)


def test_record_trade_close_compounds_across_sequential_trades(session):
    service.record_trade_close(session, realized_pnl=100.0)   # +100 -> +80 tradable, +20 reserved
    service.record_trade_close(session, realized_pnl=-30.0)   # -30 tradable
    state, ledger = service.record_trade_close(session, realized_pnl=50.0)  # +50 -> +40 tradable, +10 reserved

    assert state.today_realized_pnl == pytest.approx(100.0 - 30.0 + 50.0)
    assert ledger.reserved_capital_inr == pytest.approx(30.0)
    assert ledger.tradable_capital_inr == pytest.approx(settings.initial_capital_inr + 80 - 30 + 40)


def test_record_trade_close_scoped_to_trade_date(session):
    service.record_trade_close(session, realized_pnl=100.0, trade_date=dt.date(2026, 1, 1))
    other_day = service.load_account_state(session, trade_date=dt.date(2026, 1, 2))
    assert other_day == AccountState()
