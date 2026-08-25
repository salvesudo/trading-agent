import os

os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost/test")

from app.broker.client import FyersClient
from app.data.models import Timeframe
from app.data.service import MarketDataService, quote_from_ws_message
from app.data.store import MarketDataStore


class FakeHistoryBroker:
    def __init__(self, candles):
        self.candles = candles

    def history(self, data):
        return {"s": "ok", "candles": self.candles}


def test_quote_from_ws_message_maps_known_fields():
    message = {
        "symbol": "NSE:RELIANCE-EQ",
        "ltp": 2505.5,
        "open_price": 2490.0,
        "high_price": 2510.0,
        "low_price": 2485.0,
        "prev_close_price": 2495.0,
        "vol_traded_today": 123456,
    }
    quote = quote_from_ws_message(message)
    assert quote is not None
    assert quote.symbol == "NSE:RELIANCE-EQ"
    assert quote.ltp == 2505.5
    assert quote.volume == 123456


def test_quote_from_ws_message_returns_none_without_symbol():
    assert quote_from_ws_message({"ltp": 100.0}) is None


def test_quote_from_ws_message_returns_none_on_bad_types_instead_of_raising():
    message = {"symbol": "NSE:RELIANCE-EQ", "ltp": "not-a-number"}
    assert quote_from_ws_message(message) is None


def test_seed_history_loads_candles_into_store():
    broker = FakeHistoryBroker(
        [
            [1735600200, 2490.0, 2510.0, 2485.0, 2500.0, 100000],
            [1735600260, 2500.0, 2515.0, 2495.0, 2505.0, 120000],
        ]
    )
    client = FyersClient(broker)
    service = MarketDataService(store=MarketDataStore(), client=client)

    count = service.seed_history("NSE:RELIANCE-EQ", Timeframe.ONE_MINUTE, "2025-01-01", "2025-01-02")

    assert count == 2
    assert len(service.store.candles("NSE:RELIANCE-EQ", Timeframe.ONE_MINUTE)) == 2


def test_ingest_ws_message_updates_store():
    service = MarketDataService(store=MarketDataStore())
    service.track("NSE:RELIANCE-EQ", Timeframe.ONE_MINUTE)

    service.ingest_ws_message({
        "symbol": "NSE:RELIANCE-EQ",
        "ltp": 2500.0,
        "open_price": 2490.0,
        "high_price": 2505.0,
        "low_price": 2485.0,
        "prev_close_price": 2495.0,
        "vol_traded_today": 1000,
    })

    quote = service.store.latest_quote("NSE:RELIANCE-EQ")
    assert quote is not None
    assert quote.ltp == 2500.0


def test_ingest_ws_message_ignores_unrecognized_message():
    service = MarketDataService(store=MarketDataStore())
    service.ingest_ws_message({"unrelated": "payload"})
    assert service.store.latest_quote("NSE:RELIANCE-EQ") is None
