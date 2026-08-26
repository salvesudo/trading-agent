import datetime as dt

import pytest

from app.core.config import settings
from app.data.models import Candle
from app.paper.engine import PaperTradingEngine, PositionLimitError
from app.paper.models import ExitReason, PaperPosition
from app.risk.risk_engine import RiskDecision, RiskVerdict, TradeCandidate


def _candidate(symbol="RELIANCE", side="BUY", entry=2500.0, stop=2480.0, target=2560.0):
    return TradeCandidate(
        symbol=symbol, side=side, entry_price=entry, stop_loss=stop, target=target,
        account_equity=5000.0, estimated_costs=15.0,
    )


def _approved_verdict(qty=5):
    return RiskVerdict(decision=RiskDecision.APPROVE, approved_quantity=qty, max_loss_inr=100.0, risk_pct=2.0, reason="ok")


def _rejected_verdict():
    return RiskVerdict(decision=RiskDecision.REJECT_ZERO_QUANTITY, approved_quantity=0, max_loss_inr=0.0, risk_pct=0.0, reason="no")


def _time(hour=10, minute=0):
    return dt.datetime(2026, 1, 1, hour, minute, tzinfo=dt.timezone(dt.timedelta(hours=5, minutes=30)))  # IST


# --- opening ---

def test_open_position_creates_tracked_position():
    engine = PaperTradingEngine()
    position = engine.open_position(_candidate(), _approved_verdict(qty=7), _time())

    assert position.symbol == "RELIANCE"
    assert position.quantity == 7
    assert position.is_open
    assert engine.open_positions == [position]
    assert position.strategy is None  # optional, defaults to None when not given


def test_open_position_carries_optional_strategy_through_to_close():
    engine = PaperTradingEngine()
    engine.open_position(_candidate(), _approved_verdict(), _time(), strategy="TREND_FOLLOWING")

    closed = engine.process_price_update("RELIANCE", price=2475.0, current_time=_time(10, 5))
    assert closed.strategy == "TREND_FOLLOWING"


def test_open_position_rejects_non_approved_verdict():
    engine = PaperTradingEngine()
    with pytest.raises(ValueError):
        engine.open_position(_candidate(), _rejected_verdict(), _time())


def test_open_position_rejects_duplicate_symbol():
    engine = PaperTradingEngine()
    engine.open_position(_candidate(), _approved_verdict(), _time())
    with pytest.raises(PositionLimitError):
        engine.open_position(_candidate(), _approved_verdict(), _time())


def test_open_position_enforces_max_concurrent_positions():
    original = settings.max_concurrent_positions
    settings.max_concurrent_positions = 2
    try:
        engine = PaperTradingEngine()
        engine.open_position(_candidate(symbol="A"), _approved_verdict(), _time())
        engine.open_position(_candidate(symbol="B"), _approved_verdict(), _time())
        with pytest.raises(PositionLimitError):
            engine.open_position(_candidate(symbol="C"), _approved_verdict(), _time())
    finally:
        settings.max_concurrent_positions = original


# --- exits: stop / target ---

def test_buy_position_closes_on_stop_hit():
    engine = PaperTradingEngine()
    engine.open_position(_candidate(side="BUY", entry=2500.0, stop=2480.0, target=2560.0), _approved_verdict(), _time())

    closed = engine.process_price_update("RELIANCE", price=2475.0, current_time=_time(10, 5))
    assert closed is not None
    assert closed.exit_reason == ExitReason.STOP_LOSS
    assert closed.exit_price == 2475.0  # observed price, not the idealized 2480 stop level
    assert engine.open_positions == []
    assert engine.closed == [closed]


def test_buy_position_closes_on_target_hit():
    engine = PaperTradingEngine()
    engine.open_position(_candidate(side="BUY", entry=2500.0, stop=2480.0, target=2560.0), _approved_verdict(), _time())

    closed = engine.process_price_update("RELIANCE", price=2565.0, current_time=_time(10, 5))
    assert closed.exit_reason == ExitReason.TARGET
    assert closed.exit_price == 2565.0


def test_sell_position_closes_on_stop_hit():
    engine = PaperTradingEngine()
    engine.open_position(_candidate(side="SELL", entry=2500.0, stop=2520.0, target=2440.0), _approved_verdict(), _time())

    closed = engine.process_price_update("RELIANCE", price=2525.0, current_time=_time(10, 5))
    assert closed.exit_reason == ExitReason.STOP_LOSS


def test_sell_position_closes_on_target_hit():
    engine = PaperTradingEngine()
    engine.open_position(_candidate(side="SELL", entry=2500.0, stop=2520.0, target=2440.0), _approved_verdict(), _time())

    closed = engine.process_price_update("RELIANCE", price=2435.0, current_time=_time(10, 5))
    assert closed.exit_reason == ExitReason.TARGET


def test_price_between_stop_and_target_keeps_position_open():
    engine = PaperTradingEngine()
    engine.open_position(_candidate(side="BUY", entry=2500.0, stop=2480.0, target=2560.0), _approved_verdict(), _time())

    result = engine.process_price_update("RELIANCE", price=2510.0, current_time=_time(11, 0))
    assert result is None
    assert len(engine.open_positions) == 1


def test_no_open_position_on_symbol_returns_none():
    engine = PaperTradingEngine()
    assert engine.process_price_update("RELIANCE", price=2500.0, current_time=_time()) is None


# --- EOD square-off ---

def test_square_off_time_closes_open_position_even_between_stop_and_target():
    engine = PaperTradingEngine()
    engine.open_position(_candidate(side="BUY", entry=2500.0, stop=2480.0, target=2560.0), _approved_verdict(), _time(9, 30))

    past_close = _time(int(settings.intraday_square_off_time.split(":")[0]), int(settings.intraday_square_off_time.split(":")[1]))
    closed = engine.process_price_update("RELIANCE", price=2510.0, current_time=past_close)
    assert closed is not None
    assert closed.exit_reason == ExitReason.EOD_SQUARE_OFF
    assert closed.exit_price == 2510.0


def test_before_square_off_time_does_not_force_close():
    engine = PaperTradingEngine()
    engine.open_position(_candidate(side="BUY", entry=2500.0, stop=2480.0, target=2560.0), _approved_verdict(), _time(9, 30))

    result = engine.process_price_update("RELIANCE", price=2510.0, current_time=_time(14, 0))
    assert result is None


# --- process_candle: backtest-only, intrabar-aware exits ---

def _candle(open_, high, low, close, ts=None):
    return Candle(timestamp=ts or _time(10, 5), open=open_, high=high, low=low, close=close, volume=1000)


def test_process_candle_buy_stop_hit_intrabar_exits_at_stop_not_close():
    """The bar's close (2495) never crosses the stop -- only the low
    (2478) does. process_price_update() would have missed this
    entirely; process_candle() must not."""
    engine = PaperTradingEngine()
    engine.open_position(_candidate(side="BUY", entry=2500.0, stop=2480.0, target=2560.0), _approved_verdict(), _time())

    closed = engine.process_candle("RELIANCE", _candle(open_=2496.0, high=2497.0, low=2478.0, close=2495.0))
    assert closed is not None
    assert closed.exit_reason == ExitReason.STOP_LOSS
    assert closed.exit_price == 2480.0  # filled at the stop, no gap


def test_process_candle_buy_stop_gap_fills_at_worse_open_not_stop():
    """The bar opened below the stop (a gap down) -- a real stop order
    can't fill better than the market gapped, so the fill is at the
    open, not the nominal stop level."""
    engine = PaperTradingEngine()
    engine.open_position(_candidate(side="BUY", entry=2500.0, stop=2480.0, target=2560.0), _approved_verdict(), _time())

    closed = engine.process_candle("RELIANCE", _candle(open_=2470.0, high=2472.0, low=2465.0, close=2468.0))
    assert closed.exit_reason == ExitReason.STOP_LOSS
    assert closed.exit_price == 2470.0  # the gapped-down open, worse than 2480


def test_process_candle_buy_target_hit_intrabar_exits_at_target():
    engine = PaperTradingEngine()
    engine.open_position(_candidate(side="BUY", entry=2500.0, stop=2480.0, target=2560.0), _approved_verdict(), _time())

    closed = engine.process_candle("RELIANCE", _candle(open_=2540.0, high=2565.0, low=2538.0, close=2550.0))
    assert closed.exit_reason == ExitReason.TARGET
    assert closed.exit_price == 2560.0


def test_process_candle_buy_target_gap_fills_at_better_open_not_target():
    engine = PaperTradingEngine()
    engine.open_position(_candidate(side="BUY", entry=2500.0, stop=2480.0, target=2560.0), _approved_verdict(), _time())

    closed = engine.process_candle("RELIANCE", _candle(open_=2570.0, high=2575.0, low=2568.0, close=2572.0))
    assert closed.exit_reason == ExitReason.TARGET
    assert closed.exit_price == 2570.0  # the gapped-up open, better than 2560


def test_process_candle_both_stop_and_target_in_range_assumes_stop_first():
    """A wide bar spanning both stop (2480) and target (2560) intraday
    -- OHLC alone can't say which happened first, so the conservative
    convention (stop first) applies. A win rate should never look
    better than the data can actually support."""
    engine = PaperTradingEngine()
    engine.open_position(_candidate(side="BUY", entry=2500.0, stop=2480.0, target=2560.0), _approved_verdict(), _time())

    closed = engine.process_candle("RELIANCE", _candle(open_=2500.0, high=2565.0, low=2475.0, close=2520.0))
    assert closed.exit_reason == ExitReason.STOP_LOSS
    assert closed.exit_price == 2480.0


def test_process_candle_sell_stop_and_target_intrabar():
    engine = PaperTradingEngine()
    engine.open_position(_candidate(side="SELL", entry=2500.0, stop=2520.0, target=2440.0), _approved_verdict(), _time())

    stopped = engine.process_candle("RELIANCE", _candle(open_=2505.0, high=2525.0, low=2500.0, close=2510.0))
    assert stopped.exit_reason == ExitReason.STOP_LOSS
    assert stopped.exit_price == 2520.0


def test_process_candle_within_range_keeps_position_open():
    engine = PaperTradingEngine()
    engine.open_position(_candidate(side="BUY", entry=2500.0, stop=2480.0, target=2560.0), _approved_verdict(), _time())

    result = engine.process_candle("RELIANCE", _candle(open_=2505.0, high=2515.0, low=2495.0, close=2510.0, ts=_time(11, 0)))
    assert result is None
    assert len(engine.open_positions) == 1


def test_process_candle_square_off_uses_candle_close():
    engine = PaperTradingEngine()
    engine.open_position(_candidate(side="BUY", entry=2500.0, stop=2480.0, target=2560.0), _approved_verdict(), _time(9, 30))

    past_close = _time(int(settings.intraday_square_off_time.split(":")[0]), int(settings.intraday_square_off_time.split(":")[1]))
    closed = engine.process_candle(
        "RELIANCE", _candle(open_=2508.0, high=2512.0, low=2505.0, close=2510.0, ts=past_close)
    )
    assert closed is not None
    assert closed.exit_reason == ExitReason.EOD_SQUARE_OFF
    assert closed.exit_price == 2510.0


def test_process_candle_no_open_position_returns_none():
    engine = PaperTradingEngine()
    assert engine.process_candle("RELIANCE", _candle(open_=2500.0, high=2510.0, low=2490.0, close=2500.0)) is None


# --- manual close ---

def test_close_manually_force_closes_with_manual_reason():
    engine = PaperTradingEngine()
    engine.open_position(_candidate(), _approved_verdict(), _time())

    closed = engine.close_manually("RELIANCE", price=2505.0, current_time=_time(10, 30))
    assert closed.exit_reason == ExitReason.MANUAL
    assert engine.open_positions == []


def test_close_manually_raises_for_unknown_symbol():
    engine = PaperTradingEngine()
    with pytest.raises(KeyError):
        engine.close_manually("RELIANCE", price=2500.0, current_time=_time())


# --- restore ---

def _open_position(symbol="RELIANCE"):
    return PaperPosition(
        symbol=symbol, side="BUY", quantity=5, entry_price=2500.0, stop_loss=2480.0,
        target=2560.0, opened_at=_time(9, 30),
    )


def test_restore_position_adds_to_open_positions():
    engine = PaperTradingEngine()
    engine.restore_position(_open_position())
    assert len(engine.open_positions) == 1
    assert engine.open_positions[0].symbol == "RELIANCE"


def test_restore_position_rejects_a_closed_position():
    engine = PaperTradingEngine()
    closed = _open_position().close(2560.0, ExitReason.TARGET, _time(11, 0))
    with pytest.raises(ValueError):
        engine.restore_position(closed)


def test_restore_position_rejects_duplicate_symbol():
    engine = PaperTradingEngine()
    engine.restore_position(_open_position())
    with pytest.raises(PositionLimitError):
        engine.restore_position(_open_position())


def test_restore_position_respects_max_concurrent_positions():
    original = settings.max_concurrent_positions
    settings.max_concurrent_positions = 1
    try:
        engine = PaperTradingEngine()
        engine.restore_position(_open_position("A"))
        with pytest.raises(PositionLimitError):
            engine.restore_position(_open_position("B"))
    finally:
        settings.max_concurrent_positions = original


def test_restored_position_can_still_be_closed_normally():
    engine = PaperTradingEngine()
    engine.restore_position(_open_position())
    closed = engine.process_price_update("RELIANCE", price=2475.0, current_time=_time(10, 0))
    assert closed is not None
    assert closed.exit_reason == ExitReason.STOP_LOSS
