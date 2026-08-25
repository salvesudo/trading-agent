from datetime import datetime, timezone

from app.broker.models import Quote
from app.data.models import Candle, Timeframe
from app.data.store import MarketDataStore


def _quote(symbol="NSE:RELIANCE-EQ", ltp=100.0, volume=1000):
    return Quote(
        symbol=symbol, ltp=ltp, open=99.0, high=101.0, low=98.0,
        prev_close=99.5, volume=volume, raw={},
    )


def _ts(minute, second=0):
    return datetime(2025, 1, 1, 9, minute, second, tzinfo=timezone.utc)


def test_latest_quote_returns_none_when_untracked():
    store = MarketDataStore()
    assert store.latest_quote("NSE:RELIANCE-EQ") is None


def test_record_quote_updates_latest_quote():
    store = MarketDataStore()
    store.record_quote(_quote(ltp=105.0), ts=_ts(0))
    assert store.latest_quote("NSE:RELIANCE-EQ").ltp == 105.0


def test_record_quote_without_tracking_does_not_build_candles():
    store = MarketDataStore()
    store.record_quote(_quote(), ts=_ts(0))
    assert store.candles("NSE:RELIANCE-EQ", Timeframe.ONE_MINUTE) == []


def test_tracked_symbol_builds_candles_from_quotes():
    store = MarketDataStore()
    store.track("NSE:RELIANCE-EQ", Timeframe.ONE_MINUTE)

    store.record_quote(_quote(ltp=100.0, volume=1000), ts=_ts(0, 0))
    store.record_quote(_quote(ltp=102.0, volume=1200), ts=_ts(0, 30))
    store.record_quote(_quote(ltp=101.0, volume=1300), ts=_ts(1, 5))  # closes 09:00 candle

    closed = store.candles("NSE:RELIANCE-EQ", Timeframe.ONE_MINUTE)
    assert len(closed) == 1
    assert closed[0].open == 100.0
    assert closed[0].close == 102.0
    assert closed[0].volume == 200  # 0 (first tick) + 200 (1200-1000)

    forming = store.forming_candle("NSE:RELIANCE-EQ", Timeframe.ONE_MINUTE)
    assert forming.open == 101.0


def test_record_quote_only_feeds_matching_symbol():
    store = MarketDataStore()
    store.track("NSE:RELIANCE-EQ", Timeframe.ONE_MINUTE)
    store.record_quote(_quote(symbol="NSE:TCS-EQ", ltp=3000.0), ts=_ts(0))
    assert store.forming_candle("NSE:RELIANCE-EQ", Timeframe.ONE_MINUTE) is None
    assert store.latest_quote("NSE:TCS-EQ").ltp == 3000.0


def test_seed_candles_preloads_history_and_track_is_implicit():
    store = MarketDataStore()
    seeded = [
        Candle(timestamp=_ts(0), open=100.0, high=102.0, low=99.0, close=101.0, volume=500),
        Candle(timestamp=_ts(1), open=101.0, high=103.0, low=100.0, close=102.0, volume=600),
    ]
    store.seed_candles("NSE:RELIANCE-EQ", Timeframe.ONE_MINUTE, seeded)

    assert store.candles("NSE:RELIANCE-EQ", Timeframe.ONE_MINUTE) == seeded

    # Now live quotes append onto the seeded history via the same builder.
    store.record_quote(_quote(ltp=104.0, volume=1000), ts=_ts(2, 0))
    store.record_quote(_quote(ltp=105.0, volume=1100), ts=_ts(3, 0))  # closes 09:02

    candles = store.candles("NSE:RELIANCE-EQ", Timeframe.ONE_MINUTE)
    assert len(candles) == 3
    assert candles[-1].timestamp == _ts(2)


def test_max_candles_bounds_history_length():
    store = MarketDataStore(max_candles=2)
    store.track("NSE:RELIANCE-EQ", Timeframe.ONE_MINUTE)
    for minute in range(5):
        store.record_quote(_quote(ltp=float(minute), volume=1000 + minute * 10), ts=_ts(minute))
    # One more tick to flush the last forming candle into history.
    store.record_quote(_quote(ltp=99.0, volume=2000), ts=_ts(5))

    assert len(store.candles("NSE:RELIANCE-EQ", Timeframe.ONE_MINUTE)) <= 2
