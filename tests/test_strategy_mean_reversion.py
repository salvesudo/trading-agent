import random
from datetime import datetime, timedelta, timezone

from app.data.models import Candle
from app.regime.detector import RegimeSnapshot, TrendState, VolatilityState, detect_regime
from app.strategy import mean_reversion
from app.strategy.models import StrategyContext


def _candles(closes, ranges=None):
    ranges = ranges or [1.0] * len(closes)
    start = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
    return [
        Candle(timestamp=start + timedelta(minutes=i), open=c, high=c + r / 2, low=c - r / 2, close=c, volume=1000)
        for i, (c, r) in enumerate(zip(closes, ranges))
    ]


def _ranging_base_prices():
    # Deterministic pseudo-random chop, confirmed via detect_regime() to
    # actually classify RANGING (low ADX) -- see the strategy's own
    # docstring on requiring that gate.
    rng = random.Random(1)
    return [100 + rng.uniform(-1, 1) for _ in range(59)]


def _context(candles):
    return StrategyContext(symbol="TEST", candles=candles, regime=detect_regime(candles), news_items=[])


def test_ranging_dip_below_lower_band_generates_buy():
    prices = _ranging_base_prices() + [_ranging_base_prices()[-1] - 5]
    signal = mean_reversion.generate(_context(_candles(prices)))

    assert signal is not None
    assert signal.side == "BUY"
    assert signal.stop_loss < signal.entry_price < signal.target


def test_ranging_spike_above_upper_band_generates_sell():
    prices = _ranging_base_prices() + [_ranging_base_prices()[-1] + 5]
    signal = mean_reversion.generate(_context(_candles(prices)))

    assert signal is not None
    assert signal.side == "SELL"
    assert signal.target < signal.entry_price < signal.stop_loss


def test_ranging_but_within_bands_produces_no_signal():
    prices = _ranging_base_prices()  # no final spike -- stays inside the bands
    signal = mean_reversion.generate(_context(_candles(prices)))
    assert signal is None


def test_trending_regime_produces_no_signal_even_with_a_band_touch():
    # Strong uptrend, so even a close outside the bands shouldn't fire --
    # this strategy only trades RANGING regimes, that's the whole point.
    prices = [100.0 + i * 2.0 for i in range(60)]
    context = StrategyContext(
        symbol="TEST",
        candles=_candles(prices),
        regime=RegimeSnapshot(
            trend=TrendState.TRENDING_UP, volatility=VolatilityState.NORMAL,
            adx=40.0, plus_di=35.0, minus_di=10.0, atr_pct=1.0, atr_pct_percentile=50.0,
        ),
        news_items=[],
    )
    assert mean_reversion.generate(context) is None


def test_insufficient_data_produces_no_signal_not_an_exception():
    context = StrategyContext(
        symbol="TEST",
        candles=_candles([100.0] * 5),
        regime=RegimeSnapshot(
            trend=TrendState.RANGING, volatility=VolatilityState.NORMAL,
            adx=10.0, plus_di=10.0, minus_di=10.0, atr_pct=1.0, atr_pct_percentile=50.0,
        ),
        news_items=[],
    )
    assert mean_reversion.generate(context) is None
