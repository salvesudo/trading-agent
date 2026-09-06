import os

os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost/test")

from datetime import datetime, timezone

import pytest

from app.broker.client import FyersClient
from app.broker.models import BrokerError
from app.data.history import fetch_candles
from app.data.models import Timeframe


class FakeHistoryBroker:
    def __init__(self, candles):
        self.candles = candles
        self.last_payload = None
        self.payloads = []

    def history(self, data):
        self.last_payload = data
        self.payloads.append(data)
        return {"s": "ok", "candles": self.candles}


class FakeChunkedHistoryBroker:
    """Returns one candle per (range_from, range_to) pair it's called
    with, timestamped at that chunk's own start date -- lets a test
    verify exactly which chunks were requested, in what order, and that
    their results got stitched together correctly (chronologically,
    deduplicated), rather than just that *a* response came back."""

    def __init__(self):
        self.payloads = []

    def history(self, data):
        self.payloads.append(data)
        chunk_start = datetime.strptime(data["range_from"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        epoch = int(chunk_start.timestamp())
        return {"s": "ok", "candles": [[epoch, 100.0, 101.0, 99.0, 100.5, 1000]]}


def test_fetch_candles_parses_rows_into_candle_objects():
    broker = FakeHistoryBroker(
        [
            [1735600200, 2490.0, 2510.0, 2485.0, 2500.0, 100000],
            [1735600260, 2500.0, 2515.0, 2495.0, 2505.0, 120000],
        ]
    )
    client = FyersClient(broker)
    candles = fetch_candles(client, "NSE:RELIANCE-EQ", Timeframe.ONE_MINUTE, "2025-01-01", "2025-01-02")

    assert len(candles) == 2
    assert candles[0].open == 2490.0
    assert candles[0].volume == 100000
    assert candles[1].close == 2505.0


def test_fetch_candles_sends_correct_resolution_and_range():
    broker = FakeHistoryBroker([])
    client = FyersClient(broker)
    fetch_candles(client, "NSE:RELIANCE-EQ", Timeframe.FIVE_MINUTES, "2025-01-01", "2025-01-02")

    assert broker.last_payload["resolution"] == "5"
    assert broker.last_payload["range_from"] == "2025-01-01"
    assert broker.last_payload["range_to"] == "2025-01-02"


def test_fetch_candles_daily_resolution():
    broker = FakeHistoryBroker([])
    client = FyersClient(broker)
    fetch_candles(client, "NSE:RELIANCE-EQ", Timeframe.ONE_DAY, "2025-01-01", "2025-01-31")
    assert broker.last_payload["resolution"] == "1D"


def test_fetch_candles_empty_result():
    broker = FakeHistoryBroker([])
    client = FyersClient(broker)
    candles = fetch_candles(client, "NSE:RELIANCE-EQ", Timeframe.ONE_MINUTE, "2025-01-01", "2025-01-02")
    assert candles == []


def test_fetch_candles_rejects_malformed_row():
    broker = FakeHistoryBroker([[1735600200, 2490.0, 2510.0]])  # missing close/volume
    client = FyersClient(broker)
    with pytest.raises(BrokerError):
        fetch_candles(client, "NSE:RELIANCE-EQ", Timeframe.ONE_MINUTE, "2025-01-01", "2025-01-02")


# --- chunking (2026-09-06): FYERS caps intraday requests at 100 days,
# daily at 366 -- a range wider than that must become multiple calls,
# not one call that silently fails or truncates. ---

def test_fetch_candles_under_the_cap_makes_a_single_request():
    broker = FakeHistoryBroker([[1735600200, 2490.0, 2510.0, 2485.0, 2500.0, 100000]])
    client = FyersClient(broker)
    fetch_candles(client, "NSE:RELIANCE-EQ", Timeframe.FIVE_MINUTES, "2025-01-01", "2025-03-01")  # 59 days

    assert len(broker.payloads) == 1
    assert broker.payloads[0]["range_from"] == "2025-01-01"
    assert broker.payloads[0]["range_to"] == "2025-03-01"


def test_fetch_candles_over_the_intraday_cap_splits_into_100_day_chunks():
    broker = FakeChunkedHistoryBroker()
    client = FyersClient(broker)
    # 2025-01-01 to 2025-06-01 is 151 days -- must become 2 chunks for
    # a 100-day-capped intraday resolution.
    candles = fetch_candles(client, "NSE:RELIANCE-EQ", Timeframe.FIVE_MINUTES, "2025-01-01", "2025-06-01")

    assert len(broker.payloads) == 2
    assert broker.payloads[0]["range_from"] == "2025-01-01"
    assert broker.payloads[0]["range_to"] == "2025-04-10"  # 100 days inclusive
    assert broker.payloads[1]["range_from"] == "2025-04-11"  # no gap, no overlap
    assert broker.payloads[1]["range_to"] == "2025-06-01"
    assert len(candles) == 2  # one distinct candle per chunk, both stitched in


def test_fetch_candles_over_the_daily_cap_splits_into_366_day_chunks():
    broker = FakeChunkedHistoryBroker()
    client = FyersClient(broker)
    # 2024-01-01 to 2025-06-01 is 517 days -- must become 2 chunks for
    # a 366-day-capped daily resolution.
    fetch_candles(client, "NSE:RELIANCE-EQ", Timeframe.ONE_DAY, "2024-01-01", "2025-06-01")

    assert len(broker.payloads) == 2
    assert broker.payloads[0]["range_from"] == "2024-01-01"
    assert broker.payloads[0]["range_to"] == "2024-12-31"  # 366 days inclusive (2024 is a leap year)
    assert broker.payloads[1]["range_from"] == "2025-01-01"
    assert broker.payloads[1]["range_to"] == "2025-06-01"


def test_fetch_candles_chunks_are_ascending_and_deduplicated():
    broker = FakeChunkedHistoryBroker()
    client = FyersClient(broker)
    candles = fetch_candles(client, "NSE:RELIANCE-EQ", Timeframe.FIVE_MINUTES, "2025-01-01", "2025-06-01")

    timestamps = [c.timestamp for c in candles]
    assert timestamps == sorted(timestamps)  # each chunk's synthetic epoch happens to sort correctly
    assert len(timestamps) == len(set(timestamps))  # no duplicates leaked across chunk boundaries


def test_fetch_candles_epoch_date_format_bypasses_chunking():
    broker = FakeHistoryBroker([])
    client = FyersClient(broker)
    # A huge epoch-second range -- date_format=0 isn't chunked (nothing
    # in this codebase calls it that way), so this must stay one call.
    fetch_candles(client, "NSE:RELIANCE-EQ", Timeframe.FIVE_MINUTES, "1704067200", "1780000000", date_format=0)

    assert len(broker.payloads) == 1
    assert broker.payloads[0]["date_format"] == 0


def test_fetch_candles_rejects_range_from_after_range_to():
    broker = FakeHistoryBroker([])
    client = FyersClient(broker)
    with pytest.raises(BrokerError):
        fetch_candles(client, "NSE:RELIANCE-EQ", Timeframe.FIVE_MINUTES, "2025-06-01", "2025-01-01")
