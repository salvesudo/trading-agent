import datetime as dt
import os

os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost/test")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.broker.client import FyersClient
from app.core.config import TradingMode, settings
from app.data.models import Candle
from app.db import repository
from app.db.base import Base
from app.orchestrator import paper_trading_loop as loop
from app.paper.engine import PaperTradingEngine
from app.paper.models import ExitReason
from app.risk.risk_engine import RiskDecision, RiskVerdict, TradeCandidate


# --- the one hard safety gate this whole loop depends on ---

def test_run_forever_refuses_to_start_outside_paper_mode():
    original = settings.trading_mode
    settings.trading_mode = TradingMode.LIVE
    try:
        with pytest.raises(SystemExit):
            loop.run_forever(["NSE:RELIANCE-EQ"], max_iterations=1)
    finally:
        settings.trading_mode = original


# --- is_market_open ---

def _ist(year, month, day, hour, minute):
    from zoneinfo import ZoneInfo

    return dt.datetime(year, month, day, hour, minute, tzinfo=ZoneInfo("Asia/Kolkata"))


def test_is_market_open_during_trading_hours():
    assert loop.is_market_open(_ist(2026, 9, 7, 11, 0))  # a Monday


def test_is_market_open_before_open():
    assert not loop.is_market_open(_ist(2026, 9, 7, 9, 0))


def test_is_market_open_after_close():
    assert not loop.is_market_open(_ist(2026, 9, 7, 15, 45))


def test_is_market_open_at_exact_open_boundary():
    assert loop.is_market_open(_ist(2026, 9, 7, 9, 15))


def test_is_market_open_at_exact_close_boundary_is_closed():
    assert not loop.is_market_open(_ist(2026, 9, 7, 15, 30))


def test_is_market_open_weekend():
    saturday = _ist(2026, 9, 5, 11, 0)
    sunday = _ist(2026, 9, 6, 11, 0)
    assert not loop.is_market_open(saturday)
    assert not loop.is_market_open(sunday)


# --- _symbol_keyword ---

def test_symbol_keyword_strips_exchange_prefix_and_series_suffix():
    assert loop._symbol_keyword("NSE:RELIANCE-EQ") == "RELIANCE"
    assert loop._symbol_keyword("NSE:TATASTEEL-BE") == "TATASTEEL"


# --- process_symbol / run_cycle: DB + fake broker integration ---

class _FakeBroker:
    """Returns a fixed candle set regardless of the requested range --
    date-range mechanics are already covered by tests/test_history.py;
    this is purely about process_symbol's own decision logic."""

    def __init__(self, rows):
        self.rows = rows

    def history(self, data):
        return {"s": "ok", "candles": self.rows}


def _candle_row(epoch, close, rng=1.0):
    return [epoch, close, close + rng / 2, close - rng / 2, close, 1000]


def _ranging_then_uptrend_rows(n_range=30, n_trend=13, start=100.0, step=1.5, start_epoch=1_757_000_000):
    """Same shape as tests/test_strategy_trend.py's fixture, verified
    there to produce a fresh TREND_FOLLOWING BUY signal -- a ranging
    warm-up (so ADX actually transitions into TRENDING_UP) followed by
    a clean breakout, timestamped 5 minutes apart starting at
    `start_epoch` (a real, arbitrary September 2025 UTC moment)."""
    prices = [start]
    for i in range(1, n_range):
        prices.append(start + (1 if i % 2 == 0 else -1) * 0.8)
    for _ in range(n_trend):
        prices.append(prices[-1] + step)
    return [_candle_row(start_epoch + i * 300, p) for i, p in enumerate(prices)]


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    with Session(engine, future=True, expire_on_commit=False) as s:
        yield s


def _now():
    # 2025-09-05 10:00 UTC = 15:30 IST -- well past the ranging_then_uptrend
    # fixture's own timestamps (all in the 1_757_000_000-ish range, early
    # Sept 2025), and comfortably before the 14:45 IST entry cutoff isn't
    # actually needed here since candles carry their own timestamps --
    # `now` only needs to be used for opened_at/closed_at bookkeeping.
    # 10:20 UTC = 15:50 IST would be past square-off -- use midday IST instead.
    return dt.datetime(2025, 9, 5, 7, 0, tzinfo=dt.timezone.utc)  # 12:30 IST


def test_process_symbol_does_nothing_with_too_few_candles(session):
    client = FyersClient(_FakeBroker([_candle_row(1_757_000_000, 100.0)]))
    engine = PaperTradingEngine()
    loop.process_symbol(session, engine, client, "NSE:RELIANCE-EQ", [], _now())
    assert engine.open_positions == []
    assert engine.closed == []


def test_process_symbol_opens_a_position_on_an_approved_signal(session):
    client = FyersClient(_FakeBroker(_ranging_then_uptrend_rows()))
    engine = PaperTradingEngine()
    loop.process_symbol(session, engine, client, "NSE:RELIANCE-EQ", [], _now())

    assert len(engine.open_positions) == 1
    position = engine.open_positions[0]
    assert position.symbol == "NSE:RELIANCE-EQ"
    assert position.side == "BUY"
    assert position.strategy == "TREND_FOLLOWING"
    # persisted, not just in-memory
    assert len(repository.load_open_paper_trades(session)) == 1


def test_process_symbol_does_not_open_a_second_position_while_holding(session):
    client = FyersClient(_FakeBroker(_ranging_then_uptrend_rows()))
    engine = PaperTradingEngine()
    loop.process_symbol(session, engine, client, "NSE:RELIANCE-EQ", [], _now())
    assert len(engine.open_positions) == 1

    # Same data again -- would generate the same signal, but the symbol
    # is already held.
    loop.process_symbol(session, engine, client, "NSE:RELIANCE-EQ", [], _now())
    assert len(engine.open_positions) == 1


def test_process_symbol_closes_an_existing_position_on_stop_hit(session):
    engine = PaperTradingEngine()
    candidate = TradeCandidate(
        symbol="NSE:RELIANCE-EQ", side="BUY", entry_price=100.0, stop_loss=95.0, target=110.0,
        account_equity=5000.0, estimated_costs=5.0,
    )
    verdict = RiskVerdict(decision=RiskDecision.APPROVE, approved_quantity=5, max_loss_inr=25.0, risk_pct=0.5, reason="ok")
    from app.paper import service as paper_service

    paper_service.open_position(session, engine, candidate, verdict, opened_at=_now())
    assert len(engine.open_positions) == 1

    # Latest candle's close is below the stop -- process_symbol's own
    # exit check (process_price_update) should close it.
    client = FyersClient(_FakeBroker([_candle_row(1_757_000_000 + i * 300, 100.0 - i) for i in range(5)] + [_candle_row(1_757_000_000 + 5 * 300, 90.0)]))
    loop.process_symbol(session, engine, client, "NSE:RELIANCE-EQ", [], _now())

    assert engine.open_positions == []
    assert len(engine.closed) == 1
    assert engine.closed[0].exit_reason == ExitReason.STOP_LOSS


# --- STOP_TRADING flattening ---

def test_flatten_everything_force_closes_open_positions(session):
    engine = PaperTradingEngine()
    candidate = TradeCandidate(
        symbol="NSE:RELIANCE-EQ", side="BUY", entry_price=100.0, stop_loss=95.0, target=110.0,
        account_equity=5000.0, estimated_costs=5.0,
    )
    verdict = RiskVerdict(decision=RiskDecision.APPROVE, approved_quantity=5, max_loss_inr=25.0, risk_pct=0.5, reason="ok")
    from app.paper import service as paper_service

    paper_service.open_position(session, engine, candidate, verdict, opened_at=_now())
    client = FyersClient(_FakeBroker([_candle_row(1_757_000_000, 102.0)]))

    loop._flatten_everything(session, engine, client, _now())

    assert engine.open_positions == []
    assert len(engine.closed) == 1
    assert engine.closed[0].exit_reason == ExitReason.MANUAL


def test_stop_trading_now_reads_the_environment_fresh_not_the_singleton(monkeypatch):
    """The whole point: an .env/environment edit must be visible on the
    very next call, without anyone having mutated the long-lived
    `settings` singleton."""
    monkeypatch.setenv("STOP_TRADING", "false")
    assert loop._stop_trading_now() is False
    monkeypatch.setenv("STOP_TRADING", "true")
    assert loop._stop_trading_now() is True


def test_run_cycle_flattens_instead_of_processing_when_stop_trading_is_set(monkeypatch):
    # One shared engine/sessionmaker throughout -- run_cycle opens its
    # own session internally, and it must see the position seeded here
    # or a real persistence failure inside _flatten_everything would be
    # swallowed by its own defensive try/except and silently pass.
    db_engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=db_engine)
    session_factory = sessionmaker(bind=db_engine, future=True, expire_on_commit=False)

    engine = PaperTradingEngine()
    candidate = TradeCandidate(
        symbol="NSE:RELIANCE-EQ", side="BUY", entry_price=100.0, stop_loss=95.0, target=110.0,
        account_equity=5000.0, estimated_costs=5.0,
    )
    verdict = RiskVerdict(decision=RiskDecision.APPROVE, approved_quantity=5, max_loss_inr=25.0, risk_pct=0.5, reason="ok")
    from app.paper import service as paper_service

    with session_factory() as seed_session:
        paper_service.open_position(seed_session, engine, candidate, verdict, opened_at=_now())
        seed_session.commit()

    # STOP_TRADING is re-read fresh from the environment every cycle
    # (not the long-lived settings singleton) so an .env edit takes
    # effect on the next cycle without restarting the process -- set it
    # via the environment here to actually exercise that path.
    monkeypatch.setenv("STOP_TRADING", "true")
    called = {"fetch_all": False}

    def _fail_if_called(*args, **kwargs):
        called["fetch_all"] = True
        return []

    monkeypatch.setattr("app.orchestrator.paper_trading_loop.news_aggregator.fetch_all", _fail_if_called)
    client = FyersClient(_FakeBroker([_candle_row(1_757_000_000, 102.0)]))
    loop.run_cycle(session_factory, engine, client, ["NSE:RELIANCE-EQ"], _now())

    assert engine.open_positions == []
    assert len(engine.closed) == 1
    assert repository.load_open_paper_trades(session_factory()) == []  # actually persisted, not just in-memory
    # STOP_TRADING must skip the normal cycle entirely, not just skip opening.
    assert called["fetch_all"] is False
