"""
Technical indicators -- Phase 6.

Thin, typed wrapper around the `ta` library (EMA, RSI, MACD, ATR, ADX,
Bollinger Bands) plus a hand-rolled Supertrend, since `ta` doesn't
include one. Every function takes a `list[Candle]` (app/data/models.py)
and returns plain floats/lists -- callers never touch pandas directly,
and this module never imports app/broker or app/data.store itself; it's
a pure function of whatever candles you hand it.

Advisory only, same as every analysis-layer module in this project:
nothing here decides whether to trade. That's the Strategy Engine's job
(Phase 9), and even its output only ever becomes a *candidate* the Risk
Engine evaluates -- the Risk Engine's decision is final (spec section 47,
docs/PRINCIPLES.md section 1).

EMA/RSI/MACD/ATR/ADX/Bollinger Bands come from the well-established `ta`
library, not reimplemented here. Supertrend is hand-rolled (standard
band-flip formula) and has **not** been cross-checked against another
reference implementation or a live chart -- spot-check it before trusting
it in a strategy.

VWAP was added in Phase 9 when the VWAP strategy (app/strategy/vwap.py)
needed it -- `ta` has no session-aware VWAP, and this one resets each
trading day (see `vwap()`'s own docstring) rather than accumulating
across days, which is the standard convention for what VWAP means.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import ADXIndicator, EMAIndicator, MACD
from ta.volatility import AverageTrueRange, BollingerBands

from app.data.models import Candle


class InsufficientDataError(ValueError):
    """Raised when there aren't enough candles for a requested window,
    rather than silently handing back a mostly-NaN series that could
    leak downstream into a strategy deciding a real trade."""


def _to_dataframe(candles: List[Candle]) -> pd.DataFrame:
    if not candles:
        raise InsufficientDataError("No candles provided.")
    return pd.DataFrame(
        {
            "open": [c.open for c in candles],
            "high": [c.high for c in candles],
            "low": [c.low for c in candles],
            "close": [c.close for c in candles],
            "volume": [c.volume for c in candles],
        },
        index=[c.timestamp for c in candles],
    )


def _require_min_length(candles: List[Candle], window: int, name: str) -> None:
    if len(candles) < window:
        raise InsufficientDataError(f"{name} needs at least {window} candles, got {len(candles)}.")


def ema(candles: List[Candle], window: int = 20) -> List[float]:
    _require_min_length(candles, window, "EMA")
    df = _to_dataframe(candles)
    return EMAIndicator(df["close"], window=window).ema_indicator().tolist()


def rsi(candles: List[Candle], window: int = 14) -> List[float]:
    _require_min_length(candles, window + 1, "RSI")
    df = _to_dataframe(candles)
    return RSIIndicator(df["close"], window=window).rsi().tolist()


@dataclass(frozen=True)
class MACDResult:
    macd: List[float]
    signal: List[float]
    histogram: List[float]


def macd(
    candles: List[Candle], window_fast: int = 12, window_slow: int = 26, window_sign: int = 9
) -> MACDResult:
    _require_min_length(candles, window_slow, "MACD")
    df = _to_dataframe(candles)
    indicator = MACD(df["close"], window_slow=window_slow, window_fast=window_fast, window_sign=window_sign)
    return MACDResult(
        macd=indicator.macd().tolist(),
        signal=indicator.macd_signal().tolist(),
        histogram=indicator.macd_diff().tolist(),
    )


def atr(candles: List[Candle], window: int = 14) -> List[float]:
    _require_min_length(candles, window + 1, "ATR")
    df = _to_dataframe(candles)
    return AverageTrueRange(df["high"], df["low"], df["close"], window=window).average_true_range().tolist()


@dataclass(frozen=True)
class ADXResult:
    adx: List[float]
    plus_di: List[float]
    minus_di: List[float]


def adx(candles: List[Candle], window: int = 14) -> ADXResult:
    _require_min_length(candles, window * 2, "ADX")
    df = _to_dataframe(candles)
    indicator = ADXIndicator(df["high"], df["low"], df["close"], window=window)
    return ADXResult(
        adx=indicator.adx().tolist(),
        plus_di=indicator.adx_pos().tolist(),
        minus_di=indicator.adx_neg().tolist(),
    )


@dataclass(frozen=True)
class BollingerBandsResult:
    middle: List[float]
    upper: List[float]
    lower: List[float]
    percent_b: List[float]


def bollinger_bands(candles: List[Candle], window: int = 20, num_std: int = 2) -> BollingerBandsResult:
    _require_min_length(candles, window, "Bollinger Bands")
    df = _to_dataframe(candles)
    indicator = BollingerBands(df["close"], window=window, window_dev=num_std)
    return BollingerBandsResult(
        middle=indicator.bollinger_mavg().tolist(),
        upper=indicator.bollinger_hband().tolist(),
        lower=indicator.bollinger_lband().tolist(),
        percent_b=indicator.bollinger_pband().tolist(),
    )


@dataclass(frozen=True)
class SupertrendResult:
    value: List[float]
    direction: List[int]  # 1 = uptrend (Supertrend acts as support below price), -1 = downtrend


def supertrend(candles: List[Candle], atr_window: int = 10, multiplier: float = 3.0) -> SupertrendResult:
    """Hand-rolled -- not part of the `ta` library. Standard formula:
    bands start at (high+low)/2 +/- multiplier*ATR, then each bar's
    *final* band only ever tightens toward price (never loosens) until a
    close crosses through it, which flips the trend. That sequential
    dependency is why this is a loop, not a vectorized pandas op -- same
    reason `ta`'s own ADXIndicator is loop-based rather than vectorized.

    The very first bar has no prior trend to compare against, so its
    direction is seeded by comparing close[0] to its own bands rather
    than inherited from anywhere -- treat bar 0 as not yet meaningful,
    same as any indicator's warm-up period.
    """
    _require_min_length(candles, atr_window + 1, "Supertrend")
    df = _to_dataframe(candles)
    atr_series = AverageTrueRange(df["high"], df["low"], df["close"], window=atr_window).average_true_range()

    hl2 = (df["high"] + df["low"]) / 2
    basic_upper = hl2 + multiplier * atr_series
    basic_lower = hl2 - multiplier * atr_series
    close = df["close"]

    n = len(df)
    final_upper = [0.0] * n
    final_lower = [0.0] * n
    value = [0.0] * n
    direction = [1] * n

    for i in range(n):
        if i == 0:
            final_upper[i] = basic_upper.iloc[i]
            final_lower[i] = basic_lower.iloc[i]
            if close.iloc[i] <= final_upper[i]:
                direction[i] = -1
                value[i] = final_upper[i]
            else:
                direction[i] = 1
                value[i] = final_lower[i]
            continue

        prev_close = close.iloc[i - 1]
        final_upper[i] = (
            basic_upper.iloc[i]
            if (basic_upper.iloc[i] < final_upper[i - 1] or prev_close > final_upper[i - 1])
            else final_upper[i - 1]
        )
        final_lower[i] = (
            basic_lower.iloc[i]
            if (basic_lower.iloc[i] > final_lower[i - 1] or prev_close < final_lower[i - 1])
            else final_lower[i - 1]
        )

        if direction[i - 1] == 1:
            if close.iloc[i] < final_lower[i]:
                direction[i] = -1
                value[i] = final_upper[i]
            else:
                direction[i] = 1
                value[i] = final_lower[i]
        else:
            if close.iloc[i] > final_upper[i]:
                direction[i] = 1
                value[i] = final_lower[i]
            else:
                direction[i] = -1
                value[i] = final_upper[i]

    return SupertrendResult(value=value, direction=direction)


def vwap(candles: List[Candle]) -> List[float]:
    """Session (trading-day) VWAP -- resets at the start of each new
    day rather than accumulating across multiple days, which is the
    standard convention (VWAP is a same-day benchmark, not a
    running-forever average). Day boundaries are computed in IST
    (Asia/Kolkata), matching NSE's trading calendar, regardless of the
    timezone `candle.timestamp` happens to carry (UTC throughout this
    codebase -- see app/data/candle_builder.py)."""
    if not candles:
        raise InsufficientDataError("No candles provided.")
    from zoneinfo import ZoneInfo

    ist = ZoneInfo("Asia/Kolkata")
    result: List[float] = []
    cum_pv = 0.0
    cum_vol = 0
    current_day = None
    for c in candles:
        day = c.timestamp.astimezone(ist).date()
        if day != current_day:
            cum_pv = 0.0
            cum_vol = 0
            current_day = day
        typical_price = (c.high + c.low + c.close) / 3
        cum_pv += typical_price * c.volume
        cum_vol += c.volume
        result.append(cum_pv / cum_vol if cum_vol else typical_price)
    return result


__all__ = [
    "InsufficientDataError",
    "ema",
    "rsi",
    "macd",
    "atr",
    "adx",
    "bollinger_bands",
    "supertrend",
    "vwap",
    "MACDResult",
    "ADXResult",
    "BollingerBandsResult",
    "SupertrendResult",
]
