from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.analysis import indicators
from app.analysis.indicators import InsufficientDataError
from app.data.models import Candle

IST = ZoneInfo("Asia/Kolkata")


def _candle(hour, minute, high, low, close, volume, day=1):
    return Candle(
        timestamp=datetime(2026, 1, day, hour, minute, tzinfo=IST),
        open=close, high=high, low=low, close=close, volume=volume,
    )


def test_vwap_rejects_empty_candles():
    with pytest.raises(InsufficientDataError):
        indicators.vwap([])


def test_vwap_golden_value_two_candles_same_day():
    candles = [
        _candle(9, 15, high=102, low=98, close=100, volume=100),
        _candle(9, 16, high=112, low=108, close=110, volume=200),
    ]
    values = indicators.vwap(candles)

    # typical1 = (102+98+100)/3 = 100 -> vwap1 = 100
    assert values[0] == pytest.approx(100.0)
    # typical2 = (112+108+110)/3 = 110
    # cum_pv = 100*100 + 110*200 = 32000, cum_vol = 300 -> vwap2 = 106.666...
    assert values[1] == pytest.approx(32000 / 300)


def test_vwap_resets_at_new_trading_day():
    candles = [
        _candle(9, 15, high=200, low=200, close=200, volume=1000, day=1),  # skews day-1 VWAP high
        _candle(15, 30, high=200, low=200, close=200, volume=1000, day=1),
        _candle(9, 15, high=100, low=100, close=100, volume=50, day=2),  # new day, should reset
    ]
    values = indicators.vwap(candles)
    assert values[0] == pytest.approx(200.0)
    assert values[1] == pytest.approx(200.0)
    # Day 2's first candle should NOT be dragged toward 200 by day 1's history.
    assert values[2] == pytest.approx(100.0)


def test_vwap_zero_volume_falls_back_to_typical_price():
    candles = [_candle(9, 15, high=102, low=98, close=100, volume=0)]
    values = indicators.vwap(candles)
    assert values[0] == pytest.approx(100.0)


def test_vwap_result_length_matches_input():
    candles = [_candle(9, 15 + i, high=100 + i, low=99 + i, close=100 + i, volume=10) for i in range(5)]
    assert len(indicators.vwap(candles)) == 5


def test_vwap_utc_timestamps_convert_to_ist_for_day_boundary():
    from datetime import timezone

    # 2026-01-01 19:00 UTC = 2026-01-02 00:30 IST -- a different trading
    # day in IST even though the UTC calendar date hasn't rolled over yet.
    c1 = Candle(
        timestamp=datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc),  # 15:30 IST, day 1
        open=100, high=101, low=99, close=100, volume=1000,
    )
    c2 = Candle(
        timestamp=datetime(2026, 1, 1, 19, 0, tzinfo=timezone.utc),  # 00:30 IST, day 2
        open=50, high=51, low=49, close=50, volume=10,
    )
    values = indicators.vwap([c1, c2])
    # c2 lands on a new IST day, so it should reset rather than blend
    # with c1's much higher price.
    assert values[1] == pytest.approx(50.0)
