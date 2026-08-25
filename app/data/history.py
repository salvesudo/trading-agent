"""
Historical OHLC fetch -- Phase 4.

Wraps FyersClient.history() and parses FYERS' [epoch, o, h, l, c, v]
candle rows into typed Candle objects. Response shape follows the
documented FYERS v3 contract (`{"s": "ok", "candles": [[...], ...]}`) --
not exercised against the live endpoint from this environment; see
README's "What this environment can and can't do".
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List

from app.broker.client import FyersClient
from app.broker.models import BrokerError
from app.data.models import Candle, Timeframe


def fetch_candles(
    client: FyersClient,
    symbol: str,
    timeframe: Timeframe,
    range_from: str,
    range_to: str,
    date_format: int = 1,
) -> List[Candle]:
    """Fetch historical candles for `symbol` between `range_from` and
    `range_to` ('yyyy-mm-dd' strings when date_format=1, the default
    here; epoch-second strings when date_format=0)."""
    if timeframe is Timeframe.ONE_DAY:
        resolution = "1D"
    else:
        resolution = timeframe.value

    response = client.history(
        symbol=symbol,
        resolution=resolution,
        range_from=range_from,
        range_to=range_to,
        date_format=date_format,
    )
    raw_candles = response.get("candles", [])
    candles: List[Candle] = []
    for row in raw_candles:
        if len(row) < 6:
            raise BrokerError(f"Unexpected candle row shape from FYERS history(): {row!r}")
        epoch, o, h, l, c, v = row[:6]
        candles.append(
            Candle(
                timestamp=datetime.fromtimestamp(epoch, tz=timezone.utc),
                open=float(o),
                high=float(h),
                low=float(l),
                close=float(c),
                volume=int(v),
            )
        )
    return candles


__all__ = ["fetch_candles"]
