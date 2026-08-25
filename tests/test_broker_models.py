import pytest

from app.broker.models import (
    OrderModifyRequest,
    OrderRequest,
    OrderSide,
    OrderType,
    ProductType,
    Validity,
)


def test_order_side_maps_to_fyers_int():
    assert OrderSide.BUY.to_fyers() == 1
    assert OrderSide.SELL.to_fyers() == -1


def test_order_type_maps_to_fyers_int():
    assert OrderType.LIMIT.to_fyers() == 1
    assert OrderType.MARKET.to_fyers() == 2
    assert OrderType.STOP_MARKET.to_fyers() == 3
    assert OrderType.STOP_LIMIT.to_fyers() == 4


def test_order_request_payload_shape():
    order = OrderRequest(
        symbol="NSE:RELIANCE-EQ",
        side=OrderSide.BUY,
        quantity=2,
        order_type=OrderType.LIMIT,
        product_type=ProductType.INTRADAY,
        validity=Validity.DAY,
        limit_price=2500.0,
    )
    payload = order.to_fyers_payload()
    assert payload == {
        "symbol": "NSE:RELIANCE-EQ",
        "qty": 2,
        "type": 1,
        "side": 1,
        "productType": "INTRADAY",
        "limitPrice": 2500.0,
        "stopPrice": 0.0,
        "validity": "DAY",
        "disclosedQty": 0,
        "offlineOrder": False,
    }


def test_order_request_rejects_non_positive_quantity():
    order = OrderRequest(
        symbol="NSE:RELIANCE-EQ",
        side=OrderSide.BUY,
        quantity=0,
        order_type=OrderType.MARKET,
        product_type=ProductType.INTRADAY,
    )
    with pytest.raises(ValueError):
        order.to_fyers_payload()


def test_order_modify_request_only_includes_provided_fields():
    modification = OrderModifyRequest(order_id="123", limit_price=2510.0)
    assert modification.to_fyers_payload() == {"id": "123", "limitPrice": 2510.0}


def test_order_modify_request_with_all_fields():
    modification = OrderModifyRequest(order_id="123", limit_price=2510.0, stop_price=2490.0, quantity=5)
    assert modification.to_fyers_payload() == {
        "id": "123",
        "limitPrice": 2510.0,
        "stopPrice": 2490.0,
        "qty": 5,
    }
