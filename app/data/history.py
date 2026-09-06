"""
Historical OHLC fetch -- Phase 4.

Wraps FyersClient.history() and parses FYERS' [epoch, o, h, l, c, v]
candle rows into typed Candle objects. Response shape follows the
documented FYERS v3 contract (`{"s": "ok", "candles": [[...], ...]}`) --
not exercised against the live endpoint from this environment; see
README's "What this environment can and can't do".

Chunked automatically since 2026-09-06: FYERS caps how much range a
single history() call can cover -- 100 days for intraday resolutions
(1/2/3/5/10/15/20/30/45/60/120/180/240 minutes), 366 days for daily
("1D"). This was discovered the hard way: every backtest run so far
had (without anyone deciding this on purpose) stayed under ~100 days
for its 5-minute range, so the cap was never hit -- the first time a
longer window is actually needed (to check whether March-June 2025 was
just a broadly tough period rather than every strategy being
unfixable), a single un-chunked request would silently fail or
truncate. `fetch_candles()` now splits any range wider than the
resolution's own cap into multiple sequential requests and stitches
the results back into one ascending list. Only implemented for
date_format=1 ('yyyy-mm-dd' strings) -- nothing in this codebase has
ever called this with date_format=0 (epoch seconds), and chunking that
would need different date arithmetic; passing 0 falls back to a single
un-chunked request, same behavior as before this existed.
Source: https://support.fyers.in/portal/en/kb/fyers-api-integrations/fyers-api/api-v3/data-api
"""
from __future__ import annotations

import datetime as dt
from typing import List, Tuple

from app.broker.client import FyersClient
from app.broker.models import BrokerError
from app.data.models import Candle, Timeframe

MAX_INTRADAY_RANGE_DAYS = 100
MAX_DAILY_RANGE_DAYS = 366


def _date_chunks(range_from: str, range_to: str, max_days: int) -> List[Tuple[str, str]]:
    """Split ['range_from', 'range_to'] (inclusive, 'yyyy-mm-dd') into
    consecutive, non-overlapping sub-ranges of at most `max_days` days
    each. A single-chunk range (the common case) returns one tuple
    identical to the input -- this is a no-op for anything already
    under the cap."""
    start = dt.date.fromisoformat(range_from)
    end = dt.date.fromisoformat(range_to)
    if start > end:
        raise BrokerError(f"range_from ({range_from}) is after range_to ({range_to}).")

    chunks: List[Tuple[str, str]] = []
    chunk_start = start
    while chunk_start <= end:
        chunk_end = min(chunk_start + dt.timedelta(days=max_days - 1), end)
        chunks.append((chunk_start.isoformat(), chunk_end.isoformat()))
        chunk_start = chunk_end + dt.timedelta(days=1)
    return chunks


def _fetch_one_chunk(
    client: FyersClient, symbol: str, resolution: str, range_from: str, range_to: str, date_format: int
) -> List[Candle]:
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
                timestamp=dt.datetime.fromtimestamp(epoch, tz=dt.timezone.utc),
                open=float(o),
                high=float(h),
                low=float(l),
                close=float(c),
                volume=int(v),
            )
        )
    return candles


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
    here; epoch-second strings when date_format=0). Transparently
    chunks a range wider than FYERS' own per-request cap (see module
    docstring) into multiple requests and returns one ascending,
    deduplicated list -- callers never need to know this happened."""
    if timeframe is Timeframe.ONE_DAY:
        resolution = "1D"
        max_days = MAX_DAILY_RANGE_DAYS
    else:
        resolution = timeframe.value
        max_days = MAX_INTRADAY_RANGE_DAYS

    if date_format != 1:
        # No chunking support for epoch-second ranges -- nothing calls
        # this that way today. Single request, same as before chunking
        # existed.
        return _fetch_one_chunk(client, symbol, resolution, range_from, range_to, date_format)

    all_candles: List[Candle] = []
    seen_timestamps = set()
    for chunk_from, chunk_to in _date_chunks(range_from, range_to, max_days):
        for candle in _fetch_one_chunk(client, symbol, resolution, chunk_from, chunk_to, date_format):
            if candle.timestamp not in seen_timestamps:
                seen_timestamps.add(candle.timestamp)
                all_candles.append(candle)
    return all_candles


__all__ = ["fetch_candles", "MAX_INTRADAY_RANGE_DAYS", "MAX_DAILY_RANGE_DAYS"]
