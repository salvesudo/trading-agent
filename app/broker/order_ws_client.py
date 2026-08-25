"""
FYERS WebSocket v3 order-update client -- Phase 2.

Thin wrapper around fyers_apiv3.FyersWebsocket.order_ws.FyersOrderSocket.
Streams order/trade/position update events via callback only -- it does
not reconcile those events against this system's own records. That is
Position Reconciliation's job (Phase 15), which is expected to consume
this client rather than duplicate its connection handling.

This client is read-only by construction: nothing in this module can
place, modify, or cancel an order (that is app/broker/client.py, which
carries its own TRADING_MODE=LIVE guard). Subscribing to order updates
is safe in PAPER mode too, in principle, though PAPER mode has no real
broker-side orders to report until Phase 11 (paper trading engine)
exists.

Not exercised against the live socket from this environment (see
README.md).
"""
from __future__ import annotations

import os
from typing import Callable, Optional

from app.core.config import settings


class FyersOrderUpdateStream:
    """Callback-driven wrapper around FyersOrderSocket.

    Usage::

        stream = FyersOrderUpdateStream.from_settings(on_orders=handle_order)
        stream.connect()
        stream.subscribe("OnOrders,OnTrades,OnPositions")
        stream.keep_running()   # blocks; run in its own thread/process
    """

    def __init__(self, socket) -> None:
        self._socket = socket

    @classmethod
    def from_settings(
        cls,
        on_orders: Optional[Callable[[dict], None]] = None,
        on_trades: Optional[Callable[[dict], None]] = None,
        on_positions: Optional[Callable[[dict], None]] = None,
        on_general: Optional[Callable[[dict], None]] = None,
        on_error: Optional[Callable[[dict], None]] = None,
        on_connect: Optional[Callable[[], None]] = None,
        on_close: Optional[Callable[[dict], None]] = None,
    ) -> "FyersOrderUpdateStream":
        if not settings.fyers_app_id or not settings.fyers_access_token:
            raise RuntimeError(
                "FYERS_APP_ID / FYERS_ACCESS_TOKEN not set. Run "
                "python -m app.broker.auth first."
            )
        from fyers_apiv3.FyersWebsocket.order_ws import FyersOrderSocket

        log_dir = "logs"
        os.makedirs(log_dir, exist_ok=True)
        socket = FyersOrderSocket(
            access_token=f"{settings.fyers_app_id}:{settings.fyers_access_token}",
            log_path=log_dir,
            on_orders=on_orders,
            on_trades=on_trades,
            on_positions=on_positions,
            on_general=on_general,
            on_error=on_error,
            on_connect=on_connect,
            on_close=on_close,
            reconnect=True,
        )
        return cls(socket)

    def connect(self) -> None:
        self._socket.connect()

    def subscribe(self, data_type: str = "OnOrders,OnTrades,OnPositions") -> None:
        self._socket.subscribe(data_type)

    def keep_running(self) -> None:
        self._socket.keep_running()


__all__ = ["FyersOrderUpdateStream"]
