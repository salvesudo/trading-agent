from datetime import datetime, timedelta, timezone

import pytest

from app.analysis import indicators
from app.data.models import Candle


def _candles(closes, high_offset=0.5, low_offset=0.5, volume=1000):
    start = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
    return [
        Candle(
            timestamp=start + timedelta(minutes=i),
            open=c,
            high=c + high_offset,
            low=c - low_offset,
            close=c,
            volume=volume,
        )
        for i, c in enumerate(closes)
    ]


def _flat(n, price=100.0):
    return _candles([price] * n)


def _uptrend(n, start=100.0, step=1.0):
    return _candles([start + i * step for i in range(n)])


def _downtrend(n, start=200.0, step=1.0):
    return _candles([start - i * step for i in range(n)])


# --- shared: insufficient data ---

def test_all_indicators_reject_empty_candles():
    for fn in (indicators.ema, indicators.rsi, indicators.macd, indicators.atr,
               indicators.adx, indicators.bollinger_bands, indicators.supertrend):
        with pytest.raises(indicators.InsufficientDataError):
            fn([])


def test_ema_rejects_too_few_candles():
    with pytest.raises(indicators.InsufficientDataError):
        indicators.ema(_flat(5), window=20)


# --- EMA ---

def test_ema_of_constant_series_equals_the_constant():
    values = indicators.ema(_flat(30, price=100.0), window=10)
    assert values[-1] == pytest.approx(100.0, abs=1e-6)


def test_ema_tracks_an_uptrend_below_the_latest_close():
    candles = _uptrend(30)
    values = indicators.ema(candles, window=10)
    assert values[-1] < candles[-1].close  # EMA lags a steady uptrend


# --- RSI ---

def test_rsi_is_always_within_0_100():
    candles = _uptrend(30) + _downtrend(30, start=129.0)
    values = indicators.rsi(candles, window=14)
    valid = [v for v in values if v == v]  # drop NaN warm-up values
    assert all(0.0 <= v <= 100.0 for v in valid)


def test_rsi_approaches_100_for_pure_uptrend():
    values = indicators.rsi(_uptrend(30), window=14)
    assert values[-1] > 90.0


def test_rsi_approaches_0_for_pure_downtrend():
    values = indicators.rsi(_downtrend(30), window=14)
    assert values[-1] < 10.0


# --- MACD ---

def test_macd_is_near_zero_for_a_flat_series():
    result = indicators.macd(_flat(60), window_fast=12, window_slow=26, window_sign=9)
    assert result.macd[-1] == pytest.approx(0.0, abs=1e-6)
    assert result.histogram[-1] == pytest.approx(0.0, abs=1e-6)


def test_macd_result_lists_are_same_length_as_input():
    candles = _uptrend(60)
    result = indicators.macd(candles)
    assert len(result.macd) == len(result.signal) == len(result.histogram) == len(candles)


# --- ATR ---

def test_atr_converges_to_the_constant_true_range():
    # high-low is always 1.0 (0.5 offset each side) and closes don't gap,
    # so true range == 1.0 every bar once warmed up.
    values = indicators.atr(_flat(30), window=14)
    assert values[-1] == pytest.approx(1.0, abs=1e-6)


# --- ADX ---

def test_adx_bounded_0_100():
    candles = _uptrend(60)
    result = indicators.adx(candles, window=14)
    valid = [v for v in result.adx if v == v]
    assert all(0.0 <= v <= 100.0 for v in valid)


def test_adx_higher_for_strong_trend_than_for_flat_series():
    trending = indicators.adx(_uptrend(60), window=14).adx[-1]
    flat = indicators.adx(_flat(60), window=14).adx[-1]
    assert trending > flat


# --- Bollinger Bands ---

def test_bollinger_bands_ordering():
    result = indicators.bollinger_bands(_uptrend(40), window=20)
    for m, u, l in zip(result.middle[19:], result.upper[19:], result.lower[19:]):
        assert l <= m <= u


def test_bollinger_bands_width_zero_for_flat_series():
    result = indicators.bollinger_bands(_flat(40), window=20)
    assert result.upper[-1] == pytest.approx(result.lower[-1], abs=1e-6)


# --- Supertrend ---

def test_supertrend_uptrend_ends_below_price_in_uptrend_direction():
    candles = _uptrend(40, start=100.0, step=2.0)
    result = indicators.supertrend(candles, atr_window=10, multiplier=3.0)
    assert result.direction[-1] == 1
    assert result.value[-1] < candles[-1].close


def test_supertrend_downtrend_ends_above_price_in_downtrend_direction():
    candles = _downtrend(40, start=300.0, step=2.0)
    result = indicators.supertrend(candles, atr_window=10, multiplier=3.0)
    assert result.direction[-1] == -1
    assert result.value[-1] > candles[-1].close


def test_supertrend_result_lists_are_same_length_as_input():
    candles = _uptrend(40)
    result = indicators.supertrend(candles)
    assert len(result.value) == len(result.direction) == len(candles)


def test_supertrend_rejects_too_few_candles():
    with pytest.raises(indicators.InsufficientDataError):
        indicators.supertrend(_flat(5), atr_window=10)
