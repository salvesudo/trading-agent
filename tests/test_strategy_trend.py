from datetime import datetime, timedelta, timezone

from app.data.models import Candle
from app.regime.detector import detect_regime
from app.strategy import trend
from app.strategy.models import StrategyContext


def _candles(closes, ranges=None):
    ranges = ranges or [1.0] * len(closes)
    start = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
    return [
        Candle(timestamp=start + timedelta(minutes=i), open=c, high=c + r / 2, low=c - r / 2, close=c, volume=1000)
        for i, (c, r) in enumerate(zip(closes, ranges))
    ]


def _uptrend(n, start=100.0, step=1.5):
    return _candles([start + i * step for i in range(n)])


def _downtrend(n, start=300.0, step=1.5):
    return _candles([start - i * step for i in range(n)])


def _flat(n, price=100.0):
    return _candles([price] * n)


def _context(candles, symbol="TEST"):
    return StrategyContext(symbol=symbol, candles=candles, regime=detect_regime(candles), news_items=[])


def test_strong_uptrend_generates_buy_signal():
    candles = _uptrend(60)
    signal = trend.generate(_context(candles))
    assert signal is not None
    assert signal.side == "BUY"
    assert signal.symbol == "TEST"
    assert signal.stop_loss < signal.entry_price < signal.target
    assert 0.0 < signal.confidence <= 1.0


def test_strong_downtrend_generates_sell_signal():
    candles = _downtrend(60)
    signal = trend.generate(_context(candles))
    assert signal is not None
    assert signal.side == "SELL"
    assert signal.target < signal.entry_price < signal.stop_loss


def test_ranging_regime_produces_no_signal():
    candles = _flat(60)
    signal = trend.generate(_context(candles))
    assert signal is None


def test_insufficient_data_produces_no_signal_not_an_exception():
    candles = _flat(10)
    # Not enough candles for detect_regime itself -- build a context by
    # hand with a placeholder regime to isolate trend.py's own guard.
    from app.regime.detector import RegimeSnapshot, TrendState, VolatilityState

    context = StrategyContext(
        symbol="TEST",
        candles=candles,
        regime=RegimeSnapshot(
            trend=TrendState.TRENDING_UP, volatility=VolatilityState.NORMAL,
            adx=30.0, plus_di=25.0, minus_di=10.0, atr_pct=1.0, atr_pct_percentile=50.0,
        ),
    )
    assert trend.generate(context) is None
