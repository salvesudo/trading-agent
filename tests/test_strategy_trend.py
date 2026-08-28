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


def _ranging_then_uptrend(n_range=30, n_trend=13, start=100.0, step=1.5):
    """A ranging warm-up (so ADX starts near zero, like a real quiet
    market) followed by a clean breakout -- unlike a monotonic series
    from bar 0, this gives detect_regime() time to actually transition
    into TRENDING_UP, and lands the Supertrend flip close enough to
    that transition to still be "fresh" under MAX_BARS_SINCE_FLIP.
    Verified empirically (2026-08-28, not hand-derived): at this exact
    length, the flip is 9 bars old when the signal is generated --
    comfortably inside the 15-bar window with margin either side."""
    prices = [start]
    for i in range(1, n_range):
        prices.append(start + (1 if i % 2 == 0 else -1) * 0.8)
    for _ in range(n_trend):
        prices.append(prices[-1] + step)
    return _candles(prices)


def _ranging_then_downtrend(n_range=30, n_trend=13, start=300.0, step=1.5):
    """Mirror of _ranging_then_uptrend() -- the alternation starts on
    the opposite parity so Supertrend's pre-breakout direction lands
    on the *opposite* side from the eventual trend, which is what
    forces a genuine fresh flip right at the breakout (verified
    empirically; the naive mirror of the uptrend fixture doesn't
    reliably do this since the ranging phase's own direction is
    otherwise arbitrary)."""
    prices = [start]
    for i in range(1, n_range):
        prices.append(start + (-1 if i % 2 == 0 else 1) * 0.8)
    for _ in range(n_trend):
        prices.append(prices[-1] - step)
    return _candles(prices)


def _context(candles, symbol="TEST"):
    return StrategyContext(symbol=symbol, candles=candles, regime=detect_regime(candles), news_items=[])


def test_fresh_uptrend_generates_buy_signal():
    candles = _ranging_then_uptrend()
    signal = trend.generate(_context(candles))
    assert signal is not None
    assert signal.side == "BUY"
    assert signal.symbol == "TEST"
    assert signal.stop_loss < signal.entry_price < signal.target
    assert 0.0 < signal.confidence <= 1.0


def test_fresh_downtrend_generates_sell_signal():
    candles = _ranging_then_downtrend()
    signal = trend.generate(_context(candles))
    assert signal is not None
    assert signal.side == "SELL"
    assert signal.target < signal.entry_price < signal.stop_loss


def test_stale_trend_no_longer_generates_a_signal():
    """A long-running, monotonic trend where the Supertrend flip
    happened near bar 1 and the trend has been running for 59 bars
    since -- exactly the "confirmation lag" pattern real TREND_FOLLOWING
    trades were found losing on (docs/PRINCIPLES.md section 25).
    MAX_BARS_SINCE_FLIP exists specifically to reject this."""
    candles = _uptrend(60)
    assert trend.generate(_context(candles)) is None


def test_ranging_regime_produces_no_signal():
    candles = _flat(60)
    signal = trend.generate(_context(candles))
    assert signal is None


def test_bars_since_last_flip_zero_when_flip_is_the_last_bar():
    assert trend._bars_since_last_flip([1, 1, -1]) == 0


def test_bars_since_last_flip_counts_back_to_most_recent_flip():
    assert trend._bars_since_last_flip([-1, -1, 1, 1, 1]) == 2


def test_bars_since_last_flip_ignores_older_flips():
    # Flip at index 1 (-1->1) is older than the flip at index 3 (1->-1)
    # -- only the most recent one should count.
    assert trend._bars_since_last_flip([-1, 1, 1, -1, -1, -1]) == 2


def test_bars_since_last_flip_when_direction_never_changes():
    assert trend._bars_since_last_flip([1, 1, 1, 1]) == 3


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
