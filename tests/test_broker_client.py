import os

os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost/test")

import pytest

from app.broker.client import FyersClient
from app.broker.models import (
    BrokerError,
    OrderModifyRequest,
    OrderRequest,
    OrderSide,
    OrderType,
    PlacedOrder,
    ProductType,
)
from app.core.config import settings


class FakeBroker:
    """Implements SupportsFyersModel without ever touching a network."""

    def __init__(self):
        self.calls = []
        self.place_order_response = {"s": "ok", "id": "ORDER123"}
        self.history_response = {
            "s": "ok",
            "candles": [
                [1735600200, 2490.0, 2510.0, 2485.0, 2500.0, 100000],
                [1735600260, 2500.0, 2515.0, 2495.0, 2505.0, 120000],
            ],
        }
        self.quotes_response = {
            "s": "ok",
            "d": [
                {
                    "n": "NSE:RELIANCE-EQ",
                    "v": {
                        "lp": 2505.5,
                        "open_price": 2490.0,
                        "high_price": 2510.0,
                        "low_price": 2485.0,
                        "prev_close_price": 2495.0,
                        "volume": 123456,
                    },
                }
            ],
        }

    def get_profile(self):
        self.calls.append("get_profile")
        return {"s": "ok", "data": {"name": "Test User"}}

    def funds(self):
        return {"s": "ok", "fund_limit": []}

    def positions(self):
        return {"s": "ok", "netPositions": []}

    def holdings(self):
        return {"s": "ok", "holdings": []}

    def orderbook(self, data=None):
        return {"s": "ok", "orderBook": []}

    def tradebook(self):
        return {"s": "ok", "tradeBook": []}

    def quotes(self, data):
        self.calls.append(("quotes", data))
        return self.quotes_response

    def history(self, data):
        self.calls.append(("history", data))
        return self.history_response

    def place_order(self, data):
        self.calls.append(("place_order", data))
        return self.place_order_response

    def modify_order(self, data):
        self.calls.append(("modify_order", data))
        return {"s": "ok", "id": data["id"]}

    def cancel_order(self, data):
        self.calls.append(("cancel_order", data))
        return {"s": "ok", "id": data["id"]}


class FailingBroker(FakeBroker):
    def get_profile(self):
        return {"s": "error", "message": "invalid token"}


def make_client():
    return FyersClient(FakeBroker())


def test_profile_passes_through_on_ok():
    client = make_client()
    assert client.profile()["data"]["name"] == "Test User"


def test_read_only_call_raises_broker_error_on_non_ok():
    client = FyersClient(FailingBroker())
    with pytest.raises(BrokerError):
        client.profile()


def test_quotes_maps_response_to_quote_objects():
    client = make_client()
    result = client.quotes(["NSE:RELIANCE-EQ"])
    quote = result["NSE:RELIANCE-EQ"]
    assert quote.ltp == 2505.5
    assert quote.open == 2490.0
    assert quote.volume == 123456


def test_quotes_empty_list_returns_empty_dict_without_calling_broker():
    broker = FakeBroker()
    client = FyersClient(broker)
    assert client.quotes([]) == {}
    assert broker.calls == []


def test_quotes_rejects_more_than_fifty_symbols():
    client = make_client()
    with pytest.raises(BrokerError):
        client.quotes([f"NSE:SYM{i}-EQ" for i in range(51)])


def test_place_order_refused_in_paper_mode():
    assert not settings.is_live  # sanity: default test config is PAPER
    client = make_client()
    order = OrderRequest(
        symbol="NSE:RELIANCE-EQ",
        side=OrderSide.BUY,
        quantity=1,
        order_type=OrderType.MARKET,
        product_type=ProductType.INTRADAY,
    )
    with pytest.raises(BrokerError, match="TRADING_MODE is PAPER"):
        client.place_order(order)


def test_place_order_succeeds_in_live_mode():
    from app.core.config import TradingMode

    original_mode = settings.trading_mode
    settings.trading_mode = TradingMode.LIVE
    try:
        client = make_client()
        order = OrderRequest(
            symbol="NSE:RELIANCE-EQ",
            side=OrderSide.BUY,
            quantity=1,
            order_type=OrderType.MARKET,
            product_type=ProductType.INTRADAY,
        )
        result = client.place_order(order)
        assert isinstance(result, PlacedOrder)
        assert result.order_id == "ORDER123"
    finally:
        settings.trading_mode = original_mode


def test_modify_and_cancel_order_refused_in_paper_mode():
    client = make_client()
    with pytest.raises(BrokerError):
        client.modify_order(OrderModifyRequest(order_id="ORDER123", limit_price=2500.0))
    with pytest.raises(BrokerError):
        client.cancel_order("ORDER123")


def test_history_passes_through_and_sends_expected_payload():
    broker = FakeBroker()
    client = FyersClient(broker)
    response = client.history(
        symbol="NSE:RELIANCE-EQ",
        resolution="1",
        range_from="2025-01-01",
        range_to="2025-01-02",
    )
    assert response["candles"] == broker.history_response["candles"]
    assert broker.calls == [
        (
            "history",
            {
                "symbol": "NSE:RELIANCE-EQ",
                "resolution": "1",
                "date_format": 1,
                "range_from": "2025-01-01",
                "range_to": "2025-01-02",
                "cont_flag": 0,
            },
        )
    ]


def test_from_settings_raises_without_credentials():
    original_app_id = settings.fyers_app_id
    original_token = settings.fyers_access_token
    settings.fyers_app_id = ""
    settings.fyers_access_token = ""
    try:
        with pytest.raises(BrokerError):
            FyersClient.from_settings()
    finally:
        settings.fyers_app_id = original_app_id
        settings.fyers_access_token = original_token
