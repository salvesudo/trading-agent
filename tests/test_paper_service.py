import os

os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost/test")

import datetime as dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import repository
from app.db.base import Base
from app.paper import service
from app.paper.engine import PaperTradingEngine
from app.paper.models import ExitReason
from app.risk.risk_engine import RiskDecision, RiskVerdict, TradeCandidate


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    with Session(engine, future=True, expire_on_commit=False) as s:
        yield s


def _candidate(symbol="RELIANCE", side="BUY", entry=2500.0, stop=2480.0, target=2560.0):
    return TradeCandidate(
        symbol=symbol, side=side, entry_price=entry, stop_loss=stop, target=target,
        account_equity=5000.0, estimated_costs=15.0,
    )


def _approved(qty=5):
    return RiskVerdict(decision=RiskDecision.APPROVE, approved_quantity=qty, max_loss_inr=100.0, risk_pct=2.0, reason="ok")


def _time(hour=4, minute=0):
    # Default 4:00 UTC = 9:30 IST -- just after NSE's 9:15 open, safely
    # before the 14:45 IST no-new-entries-near-square-off cutoff
    # (settings.min_minutes_before_square_off_for_entry, added
    # 2026-08-28). The old default (9:30 UTC = 15:00 IST) was inside
    # that cutoff once it existed.
    return dt.datetime(2026, 1, 1, hour, minute, tzinfo=dt.timezone.utc)


def test_open_position_persists_immediately(session):
    engine = PaperTradingEngine()
    position = service.open_position(session, engine, _candidate(), _approved(qty=7), _time())

    assert position.symbol == "RELIANCE"
    open_rows = repository.load_open_paper_trades(session)
    assert len(open_rows) == 1
    assert open_rows[0].quantity == 7


def test_close_position_returns_none_when_still_open(session):
    engine = PaperTradingEngine()
    service.open_position(session, engine, _candidate(), _approved(), _time())

    # 07:00 UTC = 12:30 IST -- comfortably mid-session, well before the
    # 15:15 IST default square-off time.
    result = service.close_position(session, engine, "RELIANCE", price=2510.0, current_time=_time(7, 0))
    assert result is None


def test_close_position_on_target_persists_and_books_pnl(session):
    engine = PaperTradingEngine()
    service.open_position(
        session, engine, _candidate(entry=2500.0, stop=2480.0, target=2560.0), _approved(qty=5), _time()
    )

    closed = service.close_position(session, engine, "RELIANCE", price=2560.0, current_time=_time(7, 0))

    assert closed is not None
    assert closed.exit_reason == ExitReason.TARGET
    assert repository.load_open_paper_trades(session) == []
    history = repository.load_paper_trade_history(session)
    assert len(history) == 1

    account_state = repository.load_account_state(session, trade_date=dt.date(2026, 1, 1))
    expected_profit = (2560.0 - 2500.0) * 5 - 15.0  # net of the candidate's estimated_costs
    assert account_state.today_realized_pnl == pytest.approx(expected_profit)
    assert account_state.consecutive_losses == 0

    ledger = repository.load_capital_ledger(session)
    assert ledger.reserved_capital_inr == pytest.approx(expected_profit * settings.profit_reserve_pct / 100.0)


def test_close_position_on_stop_loss_increments_consecutive_losses(session):
    engine = PaperTradingEngine()
    service.open_position(
        session, engine, _candidate(entry=2500.0, stop=2480.0, target=2560.0), _approved(qty=5), _time()
    )

    closed = service.close_position(session, engine, "RELIANCE", price=2480.0, current_time=_time(7, 0))

    assert closed.exit_reason == ExitReason.STOP_LOSS
    account_state = repository.load_account_state(session, trade_date=dt.date(2026, 1, 1))
    assert account_state.today_realized_pnl == pytest.approx((2480.0 - 2500.0) * 5 - 15.0)
    assert account_state.consecutive_losses == 1


def test_close_position_manually_books_pnl_even_without_a_natural_exit(session):
    engine = PaperTradingEngine()
    service.open_position(
        session, engine, _candidate(entry=2500.0, stop=2480.0, target=2560.0), _approved(qty=5), _time()
    )

    closed = service.close_position_manually(session, engine, "RELIANCE", price=2510.0, current_time=_time(7, 0))

    assert closed.exit_reason == ExitReason.MANUAL
    assert repository.load_open_paper_trades(session) == []
    account_state = repository.load_account_state(session, trade_date=dt.date(2026, 1, 1))
    assert account_state.today_realized_pnl == pytest.approx((2510.0 - 2500.0) * 5 - 15.0)


def test_restore_open_positions_rebuilds_engine_state(session):
    original_engine = PaperTradingEngine()
    service.open_position(session, original_engine, _candidate(), _approved(qty=5), _time())
    session.commit()

    fresh_engine = PaperTradingEngine()
    restored_count = service.restore_open_positions(session, fresh_engine)

    assert restored_count == 1
    assert len(fresh_engine.open_positions) == 1
    assert fresh_engine.open_positions[0].symbol == "RELIANCE"

    # And it can be closed normally after restoration.
    closed = service.close_position(session, fresh_engine, "RELIANCE", price=2560.0, current_time=_time(7, 0))
    assert closed is not None
