from datetime import datetime, timedelta, timezone

import pytest

from app.analysis.indicators import InsufficientDataError
from app.data.models import Candle
from app.regime.detector import TrendState, VolatilityState, _percentile_rank, detect_regime


def _candles(closes, ranges=None):
    """ranges[i], if given, is the high-low width of candle i (default 1.0)."""
    ranges = ranges or [1.0] * len(closes)
    start = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
    return [
        Candle(
            timestamp=start + timedelta(minutes=i),
            open=c,
            high=c + r / 2,
            low=c - r / 2,
            close=c,
            volume=1000,
        )
        for i, (c, r) in enumerate(zip(closes, ranges))
    ]


def _flat(n, price=100.0, range_width=1.0):
    return _candles([price] * n, [range_width] * n)


def _uptrend(n, start=100.0, step=1.5):
    return _candles([start + i * step for i in range(n)])


def _downtrend(n, start=300.0, step=1.5):
    return _candles([start - i * step for i in range(n)])


# --- percentile helper ---

def test_percentile_rank_empty_history_is_neutral():
    assert _percentile_rank([], 5.0) == 50.0


def test_percentile_rank_all_lower_is_100():
    assert _percentile_rank([1.0, 2.0, 3.0], 10.0) == 100.0


def test_percentile_rank_all_higher_is_0():
    assert _percentile_rank([10.0, 20.0, 30.0], 1.0) == 0.0


def test_percentile_rank_midpoint():
    assert _percentile_rank([1.0, 2.0, 3.0, 4.0], 2.0) == 50.0


# --- trend classification ---

def test_strong_uptrend_classified_as_trending_up():
    snapshot = detect_regime(_uptrend(60))
    assert snapshot.trend == TrendState.TRENDING_UP
    assert snapshot.adx >= 25.0
    assert snapshot.plus_di > snapshot.minus_di


def test_strong_downtrend_classified_as_trending_down():
    snapshot = detect_regime(_downtrend(60))
    assert snapshot.trend == TrendState.TRENDING_DOWN
    assert snapshot.minus_di > snapshot.plus_di


def test_flat_series_classified_as_ranging():
    snapshot = detect_regime(_flat(60))
    assert snapshot.trend == TrendState.RANGING
    assert snapshot.adx < 25.0


def test_insufficient_data_raises():
    with pytest.raises(InsufficientDataError):
        detect_regime(_flat(10))


# --- volatility classification ---

def test_volatility_high_when_latest_range_much_wider_than_history():
    n = 60
    ranges = [1.0] * (n - 5) + [20.0] * 5  # last 5 bars suddenly much wider
    candles = _candles([100.0] * n, ranges)
    snapshot = detect_regime(candles, atr_window=5)
    assert snapshot.volatility == VolatilityState.HIGH
    assert snapshot.atr_pct_percentile >= 67.0


def test_volatility_low_when_latest_range_much_tighter_than_history():
    n = 60
    ranges = [20.0] * (n - 5) + [1.0] * 5  # last 5 bars suddenly much tighter
    candles = _candles([100.0] * n, ranges)
    snapshot = detect_regime(candles, atr_window=5)
    assert snapshot.volatility == VolatilityState.LOW
    assert snapshot.atr_pct_percentile <= 33.0


def test_atr_warmup_zeros_excluded_from_volatility_percentile():
    # ta's AverageTrueRange leaves the first (atr_window - 1) entries as
    # literal 0.0 while it warms up. Those fake "zero volatility" entries
    # can only ever inflate a percentile-rank computation (extra entries
    # that always count as "below or equal" to any real positive
    # reading), never deflate it -- so if detect_regime's percentile
    # matches a computation that deliberately keeps the zeros in, that
    # proves they weren't actually excluded.
    import random

    random.seed(42)
    atr_window = 14
    n = 33  # 13 warm-up zeros + 20 real entries once ATR converges
    ranges = [1.0]
    for _ in range(n - 1):
        ranges.append(max(0.2, ranges[-1] + random.uniform(-0.3, 0.3)))
    candles = _candles([100.0] * n, ranges)

    from app.analysis import indicators as ind

    atr_values = ind.atr(candles, window=atr_window)
    closes = [c.close for c in candles]
    warm_up = atr_window - 1

    naive_series = [(a / c) * 100 for a, c in zip(atr_values, closes)]  # zeros included
    correct_series = naive_series[warm_up:]  # zeros excluded

    latest = correct_series[-1]
    naive_percentile = _percentile_rank(naive_series[:-1], latest)
    correct_percentile = _percentile_rank(correct_series[:-1], latest)

    # Sanity check on the test's own premise: the naive (zero-polluted)
    # computation really would have given a different, inflated answer
    # here -- otherwise this test wouldn't be exercising anything.
    assert naive_percentile > correct_percentile

    snapshot = detect_regime(candles, adx_window=14, atr_window=atr_window)
    assert snapshot.atr_pct_percentile == pytest.approx(correct_percentile)


# --- snapshot sanity bounds ---

def test_snapshot_fields_within_expected_bounds():
    snapshot = detect_regime(_uptrend(60))
    assert 0.0 <= snapshot.adx <= 100.0
    assert 0.0 <= snapshot.plus_di <= 100.0
    assert 0.0 <= snapshot.minus_di <= 100.0
    assert snapshot.atr_pct >= 0.0
    assert 0.0 <= snapshot.atr_pct_percentile <= 100.0
