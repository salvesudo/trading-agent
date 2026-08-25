"""
Market data service -- Phase 4.

Ties together historical seeding (app/data/history.py), the live
WebSocket tick stream (app/broker/ws_client.py), and the in-memory store
(app/data/store.py) into one entry point later phases (technical
analysis, regime detection, strategy engine) depend on instead of
touching the broker layer directly.

Read-only by construction: this module never imports anything from
app/broker/client.py's order-placement methods, so there's no path from
here to a live order regardless of TRADING_MODE.

Not exercised against a live WS stream from this environment -- the WS
message parsing below is best-effort and defensive (drops an
unrecognized message rather than raising) for exactly that reason.
"""
from __future__ import annotations

from typing import List, Optional

from app.broker.client import FyersClient
from app.broker.models import Quote
from app.data.history import fetch_candles
from app.data.models import Timeframe
from app.data.store import MarketDataStore


def quote_from_ws_message(message: dict) -> Optional[Quote]:
    """Best-effort mapping from a FyersDataSocket 'SymbolUpdate' message
    (field names confirmed against the installed SDK's own parsing code,
    not live traffic) to our Quote type. Returns None rather than raising
    on a shape this doesn't recognize, so one malformed tick can't take
    down a live stream."""
    symbol = message.get("symbol")
    if not symbol:
        return None
    try:
        return Quote(
            symbol=symbol,
            ltp=float(message.get("ltp", 0.0)),
            open=float(message.get("open_price", 0.0)),
            high=float(message.get("high_price", 0.0)),
            low=float(message.get("low_price", 0.0)),
            prev_close=float(message.get("prev_close_price", 0.0)),
            volume=int(message.get("vol_traded_today", 0)),
            raw=message,
        )
    except (TypeError, ValueError):
        return None


class MarketDataService:
    def __init__(self, store: Optional[MarketDataStore] = None, client: Optional[FyersClient] = None):
        self.store = store or MarketDataStore()
        self._client = client
        self._stream = None  # set by start_streaming()

    def seed_history(
        self,
        symbol: str,
        timeframe: Timeframe,
        range_from: str,
        range_to: str,
        date_format: int = 1,
    ) -> int:
        """Fetch and load historical candles so consumers have context
        before any live ticks arrive. Returns how many candles were loaded."""
        client = self._client or FyersClient.from_settings()
        candles = fetch_candles(client, symbol, timeframe, range_from, range_to, date_format)
        self.store.seed_candles(symbol, timeframe, candles)
        return len(candles)

    def track(self, symbol: str, timeframe: Timeframe) -> None:
        self.store.track(symbol, timeframe)

    def ingest_ws_message(self, message: dict) -> None:
        """Feed one raw WS message into the store. Exposed separately
        from start_streaming() so tests can drive it without a real
        socket."""
        quote = quote_from_ws_message(message)
        if quote is not None:
            self.store.record_quote(quote)

    def start_streaming(self, symbols: List[str]) -> None:
        """Open a live WS connection and feed every tick into the store.
        Blocks the calling thread via keep_running() -- run this in a
        dedicated thread/process, same as FyersMarketDataStream itself."""
        from app.broker.ws_client import FyersMarketDataStream

        self._stream = FyersMarketDataStream.from_settings(on_message=self.ingest_ws_message)
        self._stream.connect()
        self._stream.subscribe(symbols)
        self._stream.keep_running()


__all__ = ["MarketDataService", "quote_from_ws_message"]
