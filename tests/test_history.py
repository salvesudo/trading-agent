import os

os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost/test")

import pytest

from app.broker.client import FyersClient
from app.broker.models import BrokerError
from app.data.history import fetch_candles
from app.data.models import Timeframe


class FakeHistoryBroker:
    def __init__(self, candles):
        self.candles = candles
        self.last_payload = None

    def history(self, data):
        self.last_payload = data
        return {"s": "ok", "candles": self.candles}


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
