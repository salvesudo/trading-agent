"""
Typed request/response models for the FYERS API v3 broker layer.

These are internal, repo-local types -- nothing above this layer talks
in raw FYERS wire format (integer side/type codes, `"s": "ok"` envelopes).
The rest of the codebase talks in `OrderRequest` / `PlacedOrder` / `Quote`,
and this module is the only place that knows how those map to what
FYERS actually expects on the wire.

Note this module can only *describe* an order -- it has no way to place
one. That authority belongs entirely to app/broker/client.py's
TRADING_MODE=LIVE guard, which itself never overrides the Risk Engine
(app/risk/risk_engine.py, spec section 47). See docs/PRINCIPLES.md.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

    def to_fyers(self) -> int:
        return 1 if self is OrderSide.BUY else -1


class OrderType(str, Enum):
    LIMIT = "LIMIT"
    MARKET = "MARKET"
    STOP_MARKET = "STOP_MARKET"  # FYERS SL-M
    STOP_LIMIT = "STOP_LIMIT"    # FYERS SL-L

    def to_fyers(self) -> int:
        return {
            OrderType.LIMIT: 1,
            OrderType.MARKET: 2,
            OrderType.STOP_MARKET: 3,
            OrderType.STOP_LIMIT: 4,
        }[self]


class ProductType(str, Enum):
    CNC = "CNC"
    INTRADAY = "INTRADAY"
    MARGIN = "MARGIN"
    MTF = "MTF"


class Validity(str, Enum):
    DAY = "DAY"
    IOC = "IOC"


class BrokerError(RuntimeError):
    """Raised when FYERS returns a non-'ok' envelope, or a call is
    refused locally (e.g. an order call attempted while
    TRADING_MODE != LIVE, or auth attempted with missing credentials)."""


@dataclass(frozen=True)
class OrderRequest:
    """A fully-specified order, ready to hand to the broker client.

    Deliberately *not* the same shape as `TradeCandidate`
    (app/risk/risk_engine.py): a TradeCandidate is a proposal the Risk
    Engine evaluates; an OrderRequest is what a caller builds from an
    *already-approved* RiskVerdict. Building that translation is the
    execution engine's job (a later phase) -- this module has no way to
    look at a RiskVerdict and never should, it only knows how to talk
    to the broker.
    """

    symbol: str  # e.g. "NSE:RELIANCE-EQ"
    side: OrderSide
    quantity: int
    order_type: OrderType
    product_type: ProductType
    validity: Validity = Validity.DAY
    limit_price: float = 0.0
    stop_price: float = 0.0
    disclosed_qty: int = 0
    offline_order: bool = False  # AMO order

    def to_fyers_payload(self) -> dict:
        if self.quantity <= 0:
            raise ValueError("OrderRequest.quantity must be positive.")
        return {
            "symbol": self.symbol,
            "qty": self.quantity,
            "type": self.order_type.to_fyers(),
            "side": self.side.to_fyers(),
            "productType": self.product_type.value,
            "limitPrice": self.limit_price,
            "stopPrice": self.stop_price,
            "validity": self.validity.value,
            "disclosedQty": self.disclosed_qty,
            "offlineOrder": self.offline_order,
        }


@dataclass(frozen=True)
class OrderModifyRequest:
    order_id: str
    limit_price: float | None = None
    stop_price: float | None = None
    quantity: int | None = None

    def to_fyers_payload(self) -> dict:
        payload: dict = {"id": self.order_id}
        if self.limit_price is not None:
            payload["limitPrice"] = self.limit_price
        if self.stop_price is not None:
            payload["stopPrice"] = self.stop_price
        if self.quantity is not None:
            payload["qty"] = self.quantity
        return payload


@dataclass(frozen=True)
class PlacedOrder:
    """Parsed result of a successful place_order call."""

    order_id: str
    raw_response: dict


@dataclass(frozen=True)
class Quote:
    symbol: str
    ltp: float
    open: float
    high: float
    low: float
    prev_close: float
    volume: int
    raw: dict


__all__ = [
    "OrderSide",
    "OrderType",
    "ProductType",
    "Validity",
    "BrokerError",
    "OrderRequest",
    "OrderModifyRequest",
    "PlacedOrder",
    "Quote",
]
