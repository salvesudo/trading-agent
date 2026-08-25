import pytest

from app.strategy.sizing import atr_stop_and_target


def test_buy_stop_is_below_entry_and_target_above():
    stop, target = atr_stop_and_target(100.0, atr_value=2.0, side="BUY", stop_multiple=1.5, reward_multiple=2.0)
    assert stop == pytest.approx(100.0 - 2.0 * 1.5)
    assert target == pytest.approx(100.0 + 2.0 * 1.5 * 2.0)
    assert stop < 100.0 < target


def test_sell_stop_is_above_entry_and_target_below():
    stop, target = atr_stop_and_target(100.0, atr_value=2.0, side="SELL", stop_multiple=1.5, reward_multiple=2.0)
    assert stop == pytest.approx(100.0 + 2.0 * 1.5)
    assert target == pytest.approx(100.0 - 2.0 * 1.5 * 2.0)
    assert target < 100.0 < stop


def test_rejects_invalid_side():
    with pytest.raises(ValueError):
        atr_stop_and_target(100.0, atr_value=2.0, side="HOLD", stop_multiple=1.5, reward_multiple=2.0)
