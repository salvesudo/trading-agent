"""
Pure-logic, one-tick-at-a-time candle builder -- Phase 4.

FYERS quote updates (both REST `quotes()` and the WS tick stream) carry
the day's *cumulative* traded volume, not a per-tick trade size -- see
app/broker/models.Quote.volume. This tracks the last-seen cumulative
volume and only adds the delta into the forming candle. Getting that
wrong would make every candle report the full day's volume instead of
its own, silently corrupting anything downstream that reads candle
volume (e.g. breakout/volume-confirmation logic in later phases).

No network, no I/O -- feed it timestamped (price, cumulative_volume)
ticks and it reports when a candle closed. That's what makes it fully
unit-testable without a live tick stream.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from app.data.models import Candle, Timeframe


def floor_to_bucket(ts: datetime, timeframe: Timeframe) -> datetime:
    """Round `ts` down to the start of its `timeframe` bucket (UTC-aware).

    Bucketing is anchored to the UTC epoch, not market open -- fine for
    fixed-width intraday buckets (1/5/15/30/60 min) since NSE's session
    boundaries fall on exact minute marks in every timezone.
    """
    seconds = timeframe.seconds
    epoch = ts.timestamp()
    bucket_start = epoch - (epoch % seconds)
    return datetime.fromtimestamp(bucket_start, tz=timezone.utc)


class CandleBuilder:
    """Aggregates a stream of (timestamp, price, cumulative_volume) ticks
    for one symbol into closed `Candle`s for one `Timeframe`.

    Call `update()` on every tick. It returns the just-closed Candle when
    a tick lands in a new bucket, otherwise None. `current` exposes the
    still-forming candle for callers that want a live (unclosed) view.
    """

    def __init__(self, timeframe: Timeframe):
        self.timeframe = timeframe
        self.current: Optional[Candle] = None
        self._last_cumulative_volume: Optional[int] = None

    def update(self, ts: datetime, price: float, cumulative_volume: int) -> Optional[Candle]:
        bucket_start = floor_to_bucket(ts, self.timeframe)
        volume_delta = self._consume_volume_delta(cumulative_volume)

        if self.current is None:
            self.current = Candle(bucket_start, price, price, price, price, max(volume_delta, 0))
            return None

        if bucket_start == self.current.timestamp:
            self.current = self.current.with_tick(price, volume_delta)
            return None

        if bucket_start < self.current.timestamp:
            # Out-of-order tick (e.g. a duplicate/late WS message) --
            # ignore rather than corrupt an already-forming candle.
            return None

        # Tick landed in a new bucket: the previous one is done. Gaps
        # (no ticks during a quiet bucket, e.g. an illiquid stock) are
        # simply skipped -- no zero-volume filler candles are emitted.
        closed = self.current
        self.current = Candle(bucket_start, price, price, price, price, max(volume_delta, 0))
        return closed

    def _consume_volume_delta(self, cumulative_volume: int) -> int:
        if self._last_cumulative_volume is None:
            delta = 0  # first tick ever seen: no prior baseline to diff against
        else:
            delta = cumulative_volume - self._last_cumulative_volume
            if delta < 0:
                # Cumulative volume went backwards (e.g. a new trading
                # day's counter reset) -- never let volume go negative.
                delta = 0
        self._last_cumulative_volume = cumulative_volume
        return delta


__all__ = ["CandleBuilder", "floor_to_bucket"]
