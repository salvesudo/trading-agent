from datetime import datetime, timezone

from app.data.candle_builder import CandleBuilder, floor_to_bucket
from app.data.models import Timeframe


def _ts(minute: int, second: int = 0) -> datetime:
    return datetime(2025, 1, 1, 9, minute, second, tzinfo=timezone.utc)


def test_floor_to_bucket_one_minute():
    assert floor_to_bucket(_ts(15, 37), Timeframe.ONE_MINUTE) == _ts(15, 0)


def test_floor_to_bucket_five_minutes():
    assert floor_to_bucket(_ts(17, 59), Timeframe.FIVE_MINUTES) == _ts(15, 0)
    assert floor_to_bucket(_ts(20, 0), Timeframe.FIVE_MINUTES) == _ts(20, 0)


def test_one_day_timeframe_has_no_fixed_bucket_width():
    import pytest

    with pytest.raises(ValueError):
        _ = Timeframe.ONE_DAY.seconds


def test_first_tick_opens_current_candle_without_closing_anything():
    builder = CandleBuilder(Timeframe.ONE_MINUTE)
    closed = builder.update(_ts(15, 5), price=100.0, cumulative_volume=1000)
    assert closed is None
    assert builder.current.open == 100.0
    assert builder.current.high == 100.0
    assert builder.current.low == 100.0
    assert builder.current.close == 100.0
    # First-ever tick has no prior baseline to diff against -> 0 volume.
    assert builder.current.volume == 0


def test_ticks_within_same_bucket_update_ohlc_and_accumulate_volume():
    builder = CandleBuilder(Timeframe.ONE_MINUTE)
    builder.update(_ts(15, 0), price=100.0, cumulative_volume=1000)
    builder.update(_ts(15, 20), price=105.0, cumulative_volume=1200)
    closed = builder.update(_ts(15, 40), price=98.0, cumulative_volume=1500)

    assert closed is None
    current = builder.current
    assert current.open == 100.0
    assert current.high == 105.0
    assert current.low == 98.0
    assert current.close == 98.0
    # 0 (first tick) + 200 (1200-1000) + 300 (1500-1200) = 500
    assert current.volume == 500


def test_tick_in_new_bucket_closes_previous_candle():
    builder = CandleBuilder(Timeframe.ONE_MINUTE)
    builder.update(_ts(15, 0), price=100.0, cumulative_volume=1000)
    builder.update(_ts(15, 45), price=110.0, cumulative_volume=1300)
    closed = builder.update(_ts(16, 5), price=112.0, cumulative_volume=1400)

    assert closed is not None
    assert closed.timestamp == _ts(15, 0)
    assert closed.open == 100.0
    assert closed.close == 110.0
    assert closed.volume == 300  # 0 + 300, not including the new-bucket tick

    # New candle has started, seeded by the tick that triggered the close.
    assert builder.current.timestamp == _ts(16, 0)
    assert builder.current.open == 112.0
    assert builder.current.volume == 100  # 1400 - 1300


def test_out_of_order_tick_is_ignored():
    builder = CandleBuilder(Timeframe.ONE_MINUTE)
    builder.update(_ts(16, 0), price=100.0, cumulative_volume=1000)
    closed = builder.update(_ts(15, 30), price=999.0, cumulative_volume=1)

    assert closed is None
    assert builder.current.timestamp == _ts(16, 0)
    assert builder.current.close == 100.0  # not corrupted by the stale tick


def test_volume_counter_reset_does_not_go_negative():
    builder = CandleBuilder(Timeframe.ONE_MINUTE)
    builder.update(_ts(15, 0), price=100.0, cumulative_volume=999999)
    # Simulate a new trading day's cumulative counter starting over low.
    builder.update(_ts(15, 10), price=101.0, cumulative_volume=50)

    assert builder.current.volume == 0  # negative delta clamped, not subtracted


def test_gap_between_ticks_skips_empty_buckets_without_filler_candles():
    builder = CandleBuilder(Timeframe.ONE_MINUTE)
    builder.update(_ts(15, 0), price=100.0, cumulative_volume=1000)
    # Next tick arrives 3 minutes later -- no filler candles for 15:01/15:02.
    closed = builder.update(_ts(18, 0), price=105.0, cumulative_volume=1100)

    assert closed is not None
    assert closed.timestamp == _ts(15, 0)
    assert builder.current.timestamp == _ts(18, 0)
