from datetime import datetime, timedelta, timezone

from app.data.models import Candle
from app.regime.detector import RegimeSnapshot, TrendState, VolatilityState, detect_regime
from app.strategy import vwap as vwap_strategy
from app.strategy.models import StrategyContext


def _candles(closes, range_width=1.0):
    start = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
    return [
        Candle(
            timestamp=start + timedelta(minutes=i), open=c,
            high=c + range_width / 2, low=c - range_width / 2, close=c, volume=1000,
        )
        for i, c in enumerate(closes)
    ]


def _context(candles):
    return StrategyContext(symbol="TEST", candles=candles, regime=detect_regime(candles), news_items=[])


def test_uptrend_pullback_to_vwap_generates_buy():
    # Numerically confirmed: a moderate uptrend (TRENDING_UP, ADX high)
    # followed by a small pullback lands close within 0.5x ATR of the
    # session VWAP, with close still >= VWAP.
    rally = [100 + i * 0.3 for i in range(40)]
    pullback = [rally[-1] - i * 0.5 for i in range(1, 5)]
    candles = _candles(rally + pullback, range_width=10.0)

    signal = vwap_strategy.generate(_context(candles))
    assert signal is not None
    assert signal.side == "BUY"
    assert signal.stop_loss < signal.entry_price < signal.target


def test_downtrend_pullback_to_vwap_generates_sell():
    decline = [200 - i * 0.3 for i in range(40)]
    pullback = [decline[-1] + i * 0.5 for i in range(1, 5)]
    candles = _candles(decline + pullback, range_width=10.0)

    signal = vwap_strategy.generate(_context(candles))
    assert signal is not None
    assert signal.side == "SELL"
    assert signal.target < signal.entry_price < signal.stop_loss


def test_price_far_from_vwap_produces_no_signal():
    # A long, undisturbed rally with no pullback -- price runs far ahead
    # of the session VWAP average, well outside the pullback tolerance.
    candles = _candles([100 + i * 1.5 for i in range(60)])
    signal = vwap_strategy.generate(_context(candles))
    assert signal is None


def test_ranging_regime_produces_no_signal_even_near_vwap():
    context = StrategyContext(
        symbol="TEST",
        candles=_candles([100.0] * 60),  # flat -- close is always exactly at VWAP
        regime=RegimeSnapshot(
            trend=TrendState.RANGING, volatility=VolatilityState.NORMAL,
            adx=10.0, plus_di=10.0, minus_di=10.0, atr_pct=1.0, atr_pct_percentile=50.0,
        ),
        news_items=[],
    )
    assert vwap_strategy.generate(context) is None


def test_insufficient_data_produces_no_signal_not_an_exception():
    context = StrategyContext(
        symbol="TEST",
        candles=_candles([100.0] * 5),
        regime=RegimeSnapshot(
            trend=TrendState.TRENDING_UP, volatility=VolatilityState.NORMAL,
            adx=30.0, plus_di=25.0, minus_di=10.0, atr_pct=1.0, atr_pct_percentile=50.0,
        ),
        news_items=[],
    )
    assert vwap_strategy.generate(context) is None
