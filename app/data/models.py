"""
Typed market-data models -- Phase 4.

`Candle` and `Timeframe` are the only shapes later phases (technical
analysis, regime detection, strategy engine) should need to know about;
they never see raw FYERS history rows or WS tick payloads.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class Timeframe(str, Enum):
    ONE_MINUTE = "1"
    FIVE_MINUTES = "5"
    FIFTEEN_MINUTES = "15"
    THIRTY_MINUTES = "30"
    ONE_HOUR = "60"
    ONE_DAY = "1D"

    @property
    def seconds(self) -> int:
        """Fixed bucket width, for intraday timeframes only."""
        mapping = {
            Timeframe.ONE_MINUTE: 60,
            Timeframe.FIVE_MINUTES: 5 * 60,
            Timeframe.FIFTEEN_MINUTES: 15 * 60,
            Timeframe.THIRTY_MINUTES: 30 * 60,
            Timeframe.ONE_HOUR: 60 * 60,
        }
        if self not in mapping:
            raise ValueError(
                f"{self.name} has no fixed bucket width -- fetch it via "
                "app/data/history.py instead of building it from live ticks."
            )
        return mapping[self]


@dataclass(frozen=True)
class Candle:
    timestamp: datetime  # bucket start, timezone-aware (UTC)
    open: float
    high: float
    low: float
    close: float
    volume: int

    def with_tick(self, price: float, volume_delta: int) -> "Candle":
        """Return a new Candle reflecting one more tick inside this bucket."""
        return Candle(
            timestamp=self.timestamp,
            open=self.open,
            high=max(self.high, price),
            low=min(self.low, price),
            close=price,
            volume=self.volume + max(volume_delta, 0),
        )


__all__ = ["Timeframe", "Candle"]
