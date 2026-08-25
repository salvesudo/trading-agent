"""
In-memory market data store -- Phase 4.

Holds the latest quote and recent closed candles per symbol, built live
from a tick stream via CandleBuilder. Purely in-memory; nothing here
persists across a restart -- that's Phase 5 (database) or later work.
Deliberately dumb storage with no indicator/strategy logic of its own.
"""
from __future__ import annotations

import datetime as dt
from collections import deque
from typing import Deque, Dict, List, Optional, Tuple

from app.broker.models import Quote
from app.data.candle_builder import CandleBuilder
from app.data.models import Candle, Timeframe

DEFAULT_MAX_CANDLES = 500


class MarketDataStore:
    def __init__(self, max_candles: int = DEFAULT_MAX_CANDLES):
        self._max_candles = max_candles
        self._latest_quotes: Dict[str, Quote] = {}
        self._builders: Dict[Tuple[str, Timeframe], CandleBuilder] = {}
        self._candles: Dict[Tuple[str, Timeframe], Deque[Candle]] = {}

    def track(self, symbol: str, timeframe: Timeframe) -> None:
        """Start building `timeframe` candles for `symbol` from future
        quote updates. Safe to call more than once for the same pair."""
        key = (symbol, timeframe)
        if key not in self._builders:
            self._builders[key] = CandleBuilder(timeframe)
            self._candles[key] = deque(maxlen=self._max_candles)

    def seed_candles(self, symbol: str, timeframe: Timeframe, candles: List[Candle]) -> None:
        """Preload historical candles (e.g. from app/data/history.py)
        before live ticks start arriving, so consumers have context
        immediately instead of waiting to accumulate it live."""
        self.track(symbol, timeframe)
        key = (symbol, timeframe)
        self._candles[key].clear()
        self._candles[key].extend(candles[-self._max_candles:])

    def record_quote(self, quote: Quote, ts: Optional[dt.datetime] = None) -> None:
        ts = ts or dt.datetime.now(dt.timezone.utc)
        self._latest_quotes[quote.symbol] = quote
        for (symbol, timeframe), builder in self._builders.items():
            if symbol != quote.symbol:
                continue
            closed = builder.update(ts, quote.ltp, quote.volume)
            if closed is not None:
                self._candles[(symbol, timeframe)].append(closed)

    def latest_quote(self, symbol: str) -> Optional[Quote]:
        return self._latest_quotes.get(symbol)

    def candles(self, symbol: str, timeframe: Timeframe) -> List[Candle]:
        return list(self._candles.get((symbol, timeframe), []))

    def forming_candle(self, symbol: str, timeframe: Timeframe) -> Optional[Candle]:
        builder = self._builders.get((symbol, timeframe))
        return builder.current if builder else None


__all__ = ["MarketDataStore", "DEFAULT_MAX_CANDLES"]
