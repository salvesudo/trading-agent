from datetime import datetime, timedelta, timezone

from app.data.models import Candle
from app.regime.detector import RegimeSnapshot, TrendState, VolatilityState
from app.strategy import momentum
from app.strategy.models import StrategyContext


def _candles(closes):
    start = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
    return [
        Candle(timestamp=start + timedelta(minutes=i), open=c, high=c + 0.5, low=c - 0.5, close=c, volume=1000)
        for i, c in enumerate(closes)
    ]


_PLACEHOLDER_REGIME = RegimeSnapshot(
    trend=TrendState.RANGING, volatility=VolatilityState.NORMAL,
    adx=15.0, plus_di=15.0, minus_di=15.0, atr_pct=1.0, atr_pct_percentile=50.0,
)


def _context(candles):
    # momentum.py doesn't gate on regime at all -- a placeholder is fine
    # here, unlike trend.py/mean_reversion.py's tests.
    return StrategyContext(symbol="TEST", candles=candles, regime=_PLACEHOLDER_REGIME, news_items=[])


def test_rsi_crossing_above_50_with_rising_macd_generates_buy():
    # Numerically verified: RSI goes 49.74 -> 55.27 on the last bar,
    # MACD histogram 0.104 -> 0.152 (rising, positive).
    prices = [100.0] * 20 + [100 - i * 0.15 for i in range(20)]
    prices += [prices[-1] + i * 0.25 for i in range(1, 7)]
    signal = momentum.generate(_context(_candles(prices)))

    assert signal is not None
    assert signal.side == "BUY"
    assert signal.stop_loss < signal.entry_price < signal.target


def test_rsi_crossing_below_50_with_falling_macd_generates_sell():
    # Mirror image: RSI goes 50.26 -> 44.73, MACD histogram -0.104 -> -0.152.
    prices = [100.0] * 20 + [100 + i * 0.15 for i in range(20)]
    prices += [prices[-1] - i * 0.25 for i in range(1, 7)]
    signal = momentum.generate(_context(_candles(prices)))

    assert signal is not None
    assert signal.side == "SELL"
    assert signal.target < signal.entry_price < signal.stop_loss


def test_flat_series_produces_no_signal():
    candles = _candles([100.0] * 40)
    assert momentum.generate(_context(candles)) is None


def test_no_recent_crossing_produces_no_signal():
    # A steady uptrend that crossed 50 many bars ago, not on the last bar.
    prices = [100.0] * 10 + [100 + i * 0.5 for i in range(40)]
    signal = momentum.generate(_context(_candles(prices)))
    assert signal is None


def test_insufficient_data_produces_no_signal_not_an_exception():
    candles = _candles([100.0] * 5)
    assert momentum.generate(_context(candles)) is None
