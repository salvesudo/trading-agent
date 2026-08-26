import datetime as dt

import pytest

from app.paper.models import ExitReason, PaperPosition, PositionStatus


def _position(side="BUY", entry=100.0, stop=95.0, target=110.0, qty=10):
    return PaperPosition(
        symbol="RELIANCE", side=side, quantity=qty, entry_price=entry,
        stop_loss=stop, target=target, opened_at=dt.datetime(2026, 1, 1, 9, 30, tzinfo=dt.timezone.utc),
    )


def test_new_position_is_open():
    position = _position()
    assert position.is_open
    assert position.status == PositionStatus.OPEN


def test_unrealized_pnl_buy_side():
    position = _position(side="BUY", entry=100.0, qty=10)
    assert position.unrealized_pnl(105.0) == pytest.approx(50.0)
    assert position.unrealized_pnl(95.0) == pytest.approx(-50.0)


def test_unrealized_pnl_sell_side():
    position = _position(side="SELL", entry=100.0, stop=105.0, target=90.0, qty=10)
    assert position.unrealized_pnl(95.0) == pytest.approx(50.0)
    assert position.unrealized_pnl(105.0) == pytest.approx(-50.0)


def test_close_returns_new_instance_without_mutating_original():
    position = _position()
    closed_at = dt.datetime(2026, 1, 1, 10, 0, tzinfo=dt.timezone.utc)
    closed = position.close(exit_price=110.0, reason=ExitReason.TARGET, closed_at=closed_at)

    assert position.is_open  # original untouched
    assert position.status == PositionStatus.OPEN
    assert closed.status == PositionStatus.CLOSED
    assert closed.exit_price == 110.0
    assert closed.exit_reason == ExitReason.TARGET
    assert closed.closed_at == closed_at


def test_close_raises_if_already_closed():
    position = _position()
    closed = position.close(110.0, ExitReason.TARGET, dt.datetime.now(dt.timezone.utc))
    with pytest.raises(ValueError):
        closed.close(111.0, ExitReason.TARGET, dt.datetime.now(dt.timezone.utc))


def test_realized_pnl_raises_while_still_open():
    position = _position()
    with pytest.raises(ValueError):
        position.realized_pnl()


def test_realized_pnl_buy_win():
    position = _position(side="BUY", entry=100.0, qty=10)
    closed = position.close(110.0, ExitReason.TARGET, dt.datetime.now(dt.timezone.utc))
    assert closed.realized_pnl() == pytest.approx(100.0)


def test_realized_pnl_buy_loss():
    position = _position(side="BUY", entry=100.0, qty=10)
    closed = position.close(95.0, ExitReason.STOP_LOSS, dt.datetime.now(dt.timezone.utc))
    assert closed.realized_pnl() == pytest.approx(-50.0)


def test_realized_pnl_sell_win():
    position = _position(side="SELL", entry=100.0, stop=105.0, target=90.0, qty=10)
    closed = position.close(90.0, ExitReason.TARGET, dt.datetime.now(dt.timezone.utc))
    assert closed.realized_pnl() == pytest.approx(100.0)


def test_realized_pnl_sell_loss():
    position = _position(side="SELL", entry=100.0, stop=105.0, target=90.0, qty=10)
    closed = position.close(105.0, ExitReason.STOP_LOSS, dt.datetime.now(dt.timezone.utc))
    assert closed.realized_pnl() == pytest.approx(-50.0)


def test_realized_pnl_nets_out_estimated_costs():
    """realized_pnl() must actually deduct estimated_costs, not just use
    it for sizing/approval upstream -- see the method's own docstring
    for why this was a real bug, not a style choice."""
    position = PaperPosition(
        symbol="RELIANCE", side="BUY", quantity=10, entry_price=100.0,
        stop_loss=95.0, target=110.0,
        opened_at=dt.datetime(2026, 1, 1, 9, 30, tzinfo=dt.timezone.utc),
        estimated_costs=15.0,
    )
    closed = position.close(110.0, ExitReason.TARGET, dt.datetime.now(dt.timezone.utc))
    assert closed.gross_pnl() == pytest.approx(100.0)
    assert closed.realized_pnl() == pytest.approx(100.0 - 15.0)


def test_estimated_costs_defaults_to_zero_for_backward_compatibility():
    position = _position()
    assert position.estimated_costs == 0.0
    closed = position.close(110.0, ExitReason.TARGET, dt.datetime.now(dt.timezone.utc))
    assert closed.realized_pnl() == closed.gross_pnl()


def test_close_carries_estimated_costs_forward():
    position = PaperPosition(
        symbol="RELIANCE", side="BUY", quantity=10, entry_price=100.0,
        stop_loss=95.0, target=110.0,
        opened_at=dt.datetime(2026, 1, 1, 9, 30, tzinfo=dt.timezone.utc),
        estimated_costs=15.0,
    )
    closed = position.close(110.0, ExitReason.TARGET, dt.datetime.now(dt.timezone.utc))
    assert closed.estimated_costs == 15.0
