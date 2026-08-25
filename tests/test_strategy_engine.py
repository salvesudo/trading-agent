from datetime import datetime, timedelta, timezone

from app.analysis.indicators import InsufficientDataError
from app.data.models import Candle
from app.regime.detector import RegimeSnapshot, TrendState, VolatilityState
from app.strategy.engine import DEFAULT_STRATEGIES, generate_signals, select_best_signal
from app.strategy.models import StrategyContext, StrategyName, StrategySignal

_REGIME = RegimeSnapshot(
    trend=TrendState.RANGING, volatility=VolatilityState.NORMAL,
    adx=15.0, plus_di=15.0, minus_di=15.0, atr_pct=1.0, atr_pct_percentile=50.0,
)


def _candles(n=5):
    start = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
    return [
        Candle(timestamp=start + timedelta(minutes=i), open=100, high=101, low=99, close=100, volume=1000)
        for i in range(n)
    ]


def _context():
    return StrategyContext(symbol="TEST", candles=_candles(), regime=_REGIME, news_items=[])


def _signal(name, confidence, side="BUY"):
    return StrategySignal(
        strategy=name, symbol="TEST", side=side, entry_price=100.0,
        stop_loss=98.0, target=104.0, confidence=confidence, reason="fake",
    )


def test_generate_signals_collects_every_non_none_result():
    def strat_a(ctx):
        return _signal(StrategyName.TREND_FOLLOWING, 0.5)

    def strat_b(ctx):
        return None

    def strat_c(ctx):
        return _signal(StrategyName.MOMENTUM, 0.8)

    signals = generate_signals(_context(), strategies=[strat_a, strat_b, strat_c])
    assert len(signals) == 2
    assert {s.strategy for s in signals} == {StrategyName.TREND_FOLLOWING, StrategyName.MOMENTUM}


def test_generate_signals_skips_a_strategy_that_raises_insufficient_data():
    def failing(ctx):
        raise InsufficientDataError("not enough candles")

    def working(ctx):
        return _signal(StrategyName.BREAKOUT, 0.6)

    signals = generate_signals(_context(), strategies=[failing, working])
    assert len(signals) == 1
    assert signals[0].strategy == StrategyName.BREAKOUT


def test_generate_signals_with_no_strategies_returns_empty_list():
    assert generate_signals(_context(), strategies=[]) == []


def test_default_strategies_registers_all_six():
    assert len(DEFAULT_STRATEGIES) == 6


def test_default_strategies_runs_end_to_end_without_crashing():
    # Real strategies against minimal data -- every one of them should
    # gracefully return None (insufficient data for their indicators)
    # rather than raise.
    signals = generate_signals(_context())
    assert signals == []


def test_select_best_signal_picks_highest_confidence():
    signals = [_signal(StrategyName.TREND_FOLLOWING, 0.3), _signal(StrategyName.MOMENTUM, 0.9), _signal(StrategyName.VWAP, 0.5)]
    best = select_best_signal(signals)
    assert best.strategy == StrategyName.MOMENTUM


def test_select_best_signal_empty_list_returns_none():
    assert select_best_signal([]) is None
