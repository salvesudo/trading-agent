"""
FYERS WebSocket v3 market-data client -- Phase 2.

Thin wrapper around fyers_apiv3.FyersWebsocket.data_ws.FyersDataSocket.
This module only streams quotes/depth updates via callback; it does no
buffering, candle-building, or strategy logic -- that belongs to the
Market Data Service (Phase 4) and Technical Analysis Engine (Phase 6),
which are expected to consume this client rather than duplicate its
connection handling.

Not exercised against the live socket from this environment (see
README.md). Note the wrapped SDK class caches itself as a singleton
internally (`FyersDataSocket.__new__`) -- keep that in mind if a later
phase needs more than one simultaneous data stream in one process.
"""
from __future__ import annotations

import os
from typing import Callable, Optional

from app.core.config import settings


class FyersMarketDataStream:
    """Callback-driven wrapper around FyersDataSocket.

    Usage::

        stream = FyersMarketDataStream.from_settings(on_message=handle_tick)
        stream.connect()
        stream.subscribe(["NSE:RELIANCE-EQ"])
        stream.keep_running()   # blocks; run in its own thread/process
    """

    def __init__(self, socket) -> None:
        self._socket = socket

    @classmethod
    def from_settings(
        cls,
        on_message: Optional[Callable[[dict], None]] = None,
        on_error: Optional[Callable[[dict], None]] = None,
        on_connect: Optional[Callable[[], None]] = None,
        on_close: Optional[Callable[[dict], None]] = None,
        lite_mode: bool = False,
    ) -> "FyersMarketDataStream":
        if not settings.fyers_app_id or not settings.fyers_access_token:
            raise RuntimeError(
                "FYERS_APP_ID / FYERS_ACCESS_TOKEN not set. Run "
                "python -m app.broker.auth first."
            )
        # Imported lazily so importing this module doesn't require the
        # real SDK / open log handles for code that only needs the type.
        from fyers_apiv3.FyersWebsocket.data_ws import FyersDataSocket

        log_dir = "logs"
        os.makedirs(log_dir, exist_ok=True)
        socket = FyersDataSocket(
            # This SDK expects "APP_ID:ACCESS_TOKEN", not the bare token.
            access_token=f"{settings.fyers_app_id}:{settings.fyers_access_token}",
            log_path=log_dir,
            litemode=lite_mode,
            reconnect=True,
            on_message=on_message,
            on_error=on_error,
            on_connect=on_connect,
            on_close=on_close,
        )
        return cls(socket)

    def connect(self) -> None:
        self._socket.connect()

    def subscribe(self, symbols: list[str], data_type: str = "SymbolUpdate") -> None:
        self._socket.subscribe(symbols=symbols, data_type=data_type)

    def unsubscribe(self, symbols: list[str], data_type: str = "SymbolUpdate") -> None:
        self._socket.unsubscribe(symbols=symbols, data_type=data_type)

    def keep_running(self) -> None:
        self._socket.keep_running()


__all__ = ["FyersMarketDataStream"]
