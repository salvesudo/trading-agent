"""
FYERS API v3 REST client -- Phase 2.

Thin, typed wrapper around `fyers_apiv3.fyersModel.FyersModel`. This
module owns *how* to talk to FYERS; it has no opinion on *whether* a
given trade should happen -- that authority belongs entirely to
app/risk/risk_engine.py (spec section 47, docs/PRINCIPLES.md section 1).

Every call that can create/modify/cancel a live order is gated on
`settings.is_live` at call time, independent of whatever guards exist
higher up the stack (the agent's own PAPER-only check, the Risk Engine
itself, the execution engine once it exists). This is one more layer of
the defense-in-depth pattern described in docs/PRINCIPLES.md section 12
-- a client built while TRADING_MODE=PAPER physically cannot place an
order, no matter what calls it or in what order.

Not exercised against the live API from this environment (see
README.md, "What this environment can and can't do"). Request/response
shapes follow the documented FYERS v3 REST contract as of when this was
written -- verify against FYERS' current docs before trusting this on a
real trading day; their API can and does change.
"""
from __future__ import annotations

import os
from typing import Protocol

from app.broker.models import (
    BrokerError,
    OrderModifyRequest,
    OrderRequest,
    PlacedOrder,
    Quote,
)
from app.core.config import settings


class SupportsFyersModel(Protocol):
    """Structural type for the subset of FyersModel this client uses.

    Exists so tests can inject a fake without constructing the real
    fyers_apiv3.FyersModel, which opens log file handles as a side
    effect of `__init__`.
    """

    def get_profile(self) -> dict: ...
    def funds(self) -> dict: ...
    def positions(self) -> dict: ...
    def holdings(self) -> dict: ...
    def orderbook(self, data: dict | None = None) -> dict: ...
    def tradebook(self) -> dict: ...
    def quotes(self, data: dict) -> dict: ...
    def history(self, data: dict) -> dict: ...
    def place_order(self, data: dict) -> dict: ...
    def modify_order(self, data: dict) -> dict: ...
    def cancel_order(self, data: dict) -> dict: ...


def _check_ok(response: dict, action: str) -> dict:
    if not isinstance(response, dict) or response.get("s") != "ok":
        detail = response.get("message", response) if isinstance(response, dict) else response
        raise BrokerError(f"FYERS {action} failed: {detail}")
    return response


class FyersClient:
    """Typed façade over the FYERS v3 REST API.

    Construct via `FyersClient.from_settings()` in normal use; the
    plain constructor exists so tests can pass a fake broker and never
    touch the network or the real SDK.
    """

    def __init__(self, broker: SupportsFyersModel) -> None:
        self._broker = broker

    @classmethod
    def from_settings(cls) -> "FyersClient":
        if not settings.fyers_app_id or not settings.fyers_access_token:
            raise BrokerError(
                "FYERS_APP_ID / FYERS_ACCESS_TOKEN not set. Run the daily "
                "auth flow first: python -m app.broker.auth"
            )
        # Imported lazily: constructing the real FyersModel opens log
        # file handles, which unit tests never want as a side effect of
        # importing this module.
        from fyers_apiv3.fyersModel import FyersModel

        log_dir = "logs"
        os.makedirs(log_dir, exist_ok=True)
        model = FyersModel(
            client_id=settings.fyers_app_id,
            token=settings.fyers_access_token,
            is_async=False,
            log_path=log_dir,
            log_level=settings.log_level,
        )
        return cls(model)

    # --- read-only endpoints: allowed in PAPER or LIVE ---
    # These never move money or create broker-side state, so they carry
    # no TRADING_MODE guard -- Phase 4 (market data service) and Phase
    # 15 (reconciliation) both need to read these in PAPER mode too.

    def profile(self) -> dict:
        return _check_ok(self._broker.get_profile(), "get_profile")

    def funds(self) -> dict:
        return _check_ok(self._broker.funds(), "funds")

    def positions(self) -> dict:
        return _check_ok(self._broker.positions(), "positions")

    def holdings(self) -> dict:
        return _check_ok(self._broker.holdings(), "holdings")

    def orderbook(self) -> dict:
        return _check_ok(self._broker.orderbook(), "orderbook")

    def tradebook(self) -> dict:
        return _check_ok(self._broker.tradebook(), "tradebook")

    def quotes(self, symbols: list[str]) -> dict[str, Quote]:
        if not symbols:
            return {}
        if len(symbols) > 50:
            raise BrokerError("FYERS quotes() accepts at most 50 symbols per call.")
        response = _check_ok(self._broker.quotes({"symbols": ",".join(symbols)}), "quotes")
        result: dict[str, Quote] = {}
        for item in response.get("d", []):
            v = item.get("v", {})
            symbol = item.get("n") or v.get("symbol")
            if not symbol:
                continue
            result[symbol] = Quote(
                symbol=symbol,
                ltp=float(v.get("lp", 0.0)),
                open=float(v.get("open_price", 0.0)),
                high=float(v.get("high_price", 0.0)),
                low=float(v.get("low_price", 0.0)),
                prev_close=float(v.get("prev_close_price", 0.0)),
                volume=int(v.get("volume", 0)),
                raw=item,
            )
        return result

    def history(
        self,
        symbol: str,
        resolution: str,
        range_from: str,
        range_to: str,
        date_format: int = 1,
        cont_flag: int = 0,
    ) -> dict:
        """Raw passthrough to FYERS' /history endpoint. Prefer
        app.data.history.fetch_candles() for a typed result -- this
        exists so that module has a client method to call instead of
        reaching past this client into the SDK directly."""
        payload = {
            "symbol": symbol,
            "resolution": resolution,
            "date_format": date_format,
            "range_from": range_from,
            "range_to": range_to,
            "cont_flag": cont_flag,
        }
        return _check_ok(self._broker.history(payload), "history")

    # --- order endpoints: gated on TRADING_MODE=LIVE, always ---

    def place_order(self, order: OrderRequest) -> PlacedOrder:
        self._require_live("place_order")
        response = _check_ok(self._broker.place_order(order.to_fyers_payload()), "place_order")
        return PlacedOrder(order_id=str(response.get("id", "")), raw_response=response)

    def modify_order(self, modification: OrderModifyRequest) -> dict:
        self._require_live("modify_order")
        return _check_ok(self._broker.modify_order(modification.to_fyers_payload()), "modify_order")

    def cancel_order(self, order_id: str) -> dict:
        self._require_live("cancel_order")
        return _check_ok(self._broker.cancel_order({"id": order_id}), "cancel_order")

    @staticmethod
    def _require_live(action: str) -> None:
        if not settings.is_live:
            raise BrokerError(
                f"Refusing to call {action}: TRADING_MODE is "
                f"{settings.trading_mode.value}, not LIVE. This guard is "
                "independent of the Risk Engine and the agent's own PAPER "
                "check -- see docs/PRINCIPLES.md section 12."
            )


__all__ = ["FyersClient", "SupportsFyersModel"]
