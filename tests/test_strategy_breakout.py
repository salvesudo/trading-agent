import random
from datetime import datetime, timedelta, timezone

from app.data.models import Candle
from app.regime.detector import RegimeSnapshot, TrendState, VolatilityState, detect_regime
from app.strategy import breakout
from app.strategy.models import StrategyContext

_PLACEHOLDER_REGIME = RegimeSnapshot(
    trend=TrendState.RANGING, volatility=VolatilityState.NORMAL,
    adx=15.0, plus_di=15.0, minus_di=15.0, atr_pct=1.0, atr_pct_percentile=50.0,
)


def _candles(closes, ranges=None):
    ranges = ranges or [1.0] * len(closes)
    start = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
    return [
        Candle(timestamp=start + timedelta(minutes=i), open=c, high=c + r / 2, low=c - r / 2, close=c, volume=1000)
        for i, (c, r) in enumerate(zip(closes, ranges))
    ]


def _squeeze_then_move(bump: float):
    # Deterministic: wide chop (so the squeeze isn't the whole history),
    # then a genuine tight consolidation, then one bar moving `bump`
    # beyond the squeeze -- numerically confirmed to both break the
    # 20-bar range and keep the width percentile inside the squeeze
    # threshold (a strong enough move widens the current bar's own
    # contribution to band width and defeats the squeeze condition).
    rng = random.Random(2)
    wide = [100 + rng.uniform(-3, 3) for _ in range(30)]
    squeeze = [100 + rng.uniform(-0.3, 0.3) for _ in range(20)]
    return wide + squeeze + [squeeze[-1] + bump]


def _context(candles):
    return StrategyContext(symbol="TEST", candles=candles, regime=detect_regime(candles), news_items=[])


def test_squeeze_then_upside_break_generates_buy():
    signal = breakout.generate(_context(_candles(_squeeze_then_move(1.0))))
    assert signal is not None
    assert signal.side == "BUY"
    assert signal.stop_loss < signal.entry_price < signal.target


def test_squeeze_then_downside_break_generates_sell():
    signal = breakout.generate(_context(_candles(_squeeze_then_move(-1.0))))
    assert signal is not None
    assert signal.side == "SELL"
    assert signal.target < signal.entry_price < signal.stop_loss


def test_move_without_prior_squeeze_produces_no_signal():
    # Consistently wide/choppy the whole way through, then a big final
    # move -- no consolidation beforehand, so this isn't a squeeze
    # breakout even though the move itself is large.
    rng = random.Random(3)
    prices = [100 + rng.uniform(-3, 3) for _ in range(50)] + [130]
    signal = breakout.generate(_context(_candles(prices)))
    assert signal is None


def test_squeeze_without_a_break_produces_no_signal():
    rng = random.Random(2)
    wide = [100 + rng.uniform(-3, 3) for _ in range(30)]
    squeeze = [100 + rng.uniform(-0.3, 0.3) for _ in range(20)]
    signal = breakout.generate(_context(_candles(wide + squeeze)))  # no final breakout bar
    assert signal is None


def test_insufficient_data_produces_no_signal_not_an_exception():
    # breakout.py's own LOOKBACK gate (needs LOOKBACK + 1 candles) fires
    # before any indicator call, so a placeholder regime (rather than a
    # real detect_regime() call, which needs 28 candles itself) isolates
    # breakout.py's own guard specifically.
    context = StrategyContext(
        symbol="TEST", candles=_candles([100.0] * 10), regime=_PLACEHOLDER_REGIME, news_items=[]
    )
    assert breakout.generate(context) is None
