import os

os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost/test")

import datetime as dt

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.data.models import Candle, Timeframe
from app.db import repository
from app.db.base import Base
from app.risk.risk_engine import AccountState, RiskDecision, RiskVerdict, TradeCandidate
from app.security.compliance import CheckResult, ComplianceReport


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    with Session(engine, future=True, expire_on_commit=False) as s:
        yield s


def test_load_account_state_defaults_when_no_row_exists(session):
    state = repository.load_account_state(session, trade_date=dt.date(2026, 1, 1))
    assert state == AccountState()


def test_save_and_load_account_state_round_trips(session):
    state = AccountState(today_realized_pnl=-150.0, consecutive_losses=2, system_healthy=False)
    repository.save_account_state(session, state, trade_date=dt.date(2026, 1, 1))

    loaded = repository.load_account_state(session, trade_date=dt.date(2026, 1, 1))
    assert loaded == state


def test_save_account_state_upserts_same_day():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    with Session(engine, future=True, expire_on_commit=False) as s:
        repository.save_account_state(s, AccountState(consecutive_losses=1), trade_date=dt.date(2026, 1, 1))
        repository.save_account_state(s, AccountState(consecutive_losses=2), trade_date=dt.date(2026, 1, 1))
        s.commit()

        from sqlalchemy import select
        from app.db.models import AccountStateRow

        rows = s.scalars(select(AccountStateRow)).all()
        assert len(rows) == 1
        assert rows[0].consecutive_losses == 2


def test_load_account_state_is_scoped_to_trade_date(session):
    repository.save_account_state(session, AccountState(consecutive_losses=5), trade_date=dt.date(2026, 1, 1))
    other_day = repository.load_account_state(session, trade_date=dt.date(2026, 1, 2))
    assert other_day == AccountState()  # unaffected by the other day's row


def test_save_risk_evaluation_persists_candidate_and_verdict(session):
    candidate = TradeCandidate(
        symbol="RELIANCE", side="BUY", entry_price=2500.0, stop_loss=2480.0,
        target=2560.0, account_equity=5000.0, estimated_costs=15.0,
    )
    verdict = RiskVerdict(
        decision=RiskDecision.APPROVE, approved_quantity=2, max_loss_inr=40.0,
        risk_pct=0.8, reason="Approved: qty=2",
    )
    row = repository.save_risk_evaluation(session, candidate, verdict)
    assert row.id is not None
    assert row.symbol == "RELIANCE"
    assert row.decision == "APPROVE"
    assert row.approved_quantity == 2


def test_save_compliance_report_persists_all_checks(session):
    report = ComplianceReport(checks=[
        CheckResult("static_ip", True, "matches"),
        CheckResult("session_valid", False, "expired"),
    ])
    rows = repository.save_compliance_report(session, report)
    assert len(rows) == 2
    assert {r.check_name for r in rows} == {"static_ip", "session_valid"}
    assert rows[0].ok is True
    assert rows[1].ok is False


def _candle(minute, price=100.0, volume=1000):
    return Candle(
        timestamp=dt.datetime(2026, 1, 1, 9, minute, tzinfo=dt.timezone.utc),
        open=price, high=price + 1, low=price - 1, close=price, volume=volume,
    )


def test_loaded_candle_timestamp_is_tz_aware_despite_sqlite_stripping_it(session):
    # SQLite's DateTime(timezone=True) doesn't actually preserve tzinfo
    # across a round trip -- this pins that repository.load_candles()
    # re-attaches UTC rather than silently handing back a naive datetime.
    repository.save_candles(session, "NSE:RELIANCE-EQ", Timeframe.ONE_MINUTE, [_candle(0)])
    loaded = repository.load_candles(session, "NSE:RELIANCE-EQ", Timeframe.ONE_MINUTE)
    assert loaded[0].timestamp.tzinfo is not None


def test_save_and_load_candles_round_trip(session):
    candles = [_candle(0), _candle(1), _candle(2)]
    count = repository.save_candles(session, "NSE:RELIANCE-EQ", Timeframe.ONE_MINUTE, candles)
    assert count == 3

    loaded = repository.load_candles(session, "NSE:RELIANCE-EQ", Timeframe.ONE_MINUTE)
    assert len(loaded) == 3
    assert loaded[0].timestamp == candles[0].timestamp
    assert loaded == candles


def test_save_candles_skips_duplicates_on_reseed(session):
    candles = [_candle(0), _candle(1)]
    repository.save_candles(session, "NSE:RELIANCE-EQ", Timeframe.ONE_MINUTE, candles)
    second_count = repository.save_candles(
        session, "NSE:RELIANCE-EQ", Timeframe.ONE_MINUTE, candles + [_candle(2)]
    )
    assert second_count == 1  # only the new one (minute=2) got inserted

    loaded = repository.load_candles(session, "NSE:RELIANCE-EQ", Timeframe.ONE_MINUTE)
    assert len(loaded) == 3


def test_save_candles_empty_list_is_a_noop(session):
    assert repository.save_candles(session, "NSE:RELIANCE-EQ", Timeframe.ONE_MINUTE, []) == 0


def test_load_candles_respects_limit_and_stays_ascending(session):
    candles = [_candle(m) for m in range(5)]
    repository.save_candles(session, "NSE:RELIANCE-EQ", Timeframe.ONE_MINUTE, candles)

    loaded = repository.load_candles(session, "NSE:RELIANCE-EQ", Timeframe.ONE_MINUTE, limit=2)
    assert len(loaded) == 2
    assert loaded[0].timestamp < loaded[1].timestamp
    assert loaded[-1].timestamp == candles[-1].timestamp  # most recent kept


def test_candles_are_scoped_by_symbol_and_timeframe(session):
    repository.save_candles(session, "NSE:RELIANCE-EQ", Timeframe.ONE_MINUTE, [_candle(0)])
    repository.save_candles(session, "NSE:TCS-EQ", Timeframe.ONE_MINUTE, [_candle(0)])
    repository.save_candles(session, "NSE:RELIANCE-EQ", Timeframe.FIVE_MINUTES, [_candle(0)])

    assert len(repository.load_candles(session, "NSE:RELIANCE-EQ", Timeframe.ONE_MINUTE)) == 1
    assert len(repository.load_candles(session, "NSE:TCS-EQ", Timeframe.ONE_MINUTE)) == 1
    assert len(repository.load_candles(session, "NSE:RELIANCE-EQ", Timeframe.FIVE_MINUTES)) == 1
