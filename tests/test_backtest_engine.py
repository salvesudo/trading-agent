from datetime import datetime, timedelta, timezone

import pytest

from app.analysis.indicators import InsufficientDataError
from app.backtest.engine import run_backtest
from app.data.models import Candle
from app.paper.models import ExitReason


def _candles(closes, ranges=None):
    ranges = ranges or [1.0] * len(closes)
    start = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
    return [
        Candle(timestamp=start + timedelta(minutes=i), open=c, high=c + r / 2, low=c - r / 2, close=c, volume=1000)
        for i, (c, r) in enumerate(zip(closes, ranges))
    ]


def test_rejects_fewer_than_two_candles():
    with pytest.raises(InsufficientDataError):
        run_backtest(_candles([100.0]), "TEST")


def test_flat_series_produces_no_trades_and_unchanged_equity():
    result = run_backtest(_candles([100.0] * 60), "TEST")
    assert result.total_trades == 0
    assert result.wins == 0
    assert result.losses == 0
    assert result.total_realized_pnl_inr == 0.0
    assert result.ending_total_equity_inr == pytest.approx(result.starting_capital_inr)
    assert result.max_drawdown_pct == 0.0
    assert result.per_strategy == []
    assert result.net_return_pct == pytest.approx(0.0)


def test_sustained_uptrend_produces_mostly_winning_trend_following_trades():
    # Verified numerically: a long, strong, steady uptrend repeatedly
    # triggers TREND_FOLLOWING BUY signals as each position exits and a
    # new one opens -- 80 trades, 79 wins, 1 loss on this exact series.
    prices = [100 + i * 1.5 for i in range(120)]
    result = run_backtest(_candles(prices), "TEST")

    assert result.total_trades > 0
    assert result.wins > result.losses
    assert result.total_realized_pnl_inr > 0
    assert result.ending_total_equity_inr > result.starting_capital_inr
    assert len(result.per_strategy) == 1
    assert result.per_strategy[0].strategy == "TREND_FOLLOWING"
    assert result.per_strategy[0].trade_count == result.total_trades
    assert result.win_rate_pct == pytest.approx(result.wins / result.total_trades * 100)


def test_uptrend_then_reversal_produces_a_losing_trade_and_positive_drawdown():
    # Verified numerically: 14 trades, 11 wins, 3 losses, small positive
    # drawdown once the reversal starts giving back gains.
    prices = [100 + i * 1.5 for i in range(40)] + [100 + 39 * 1.5 - i * 3 for i in range(1, 15)]
    result = run_backtest(_candles(prices), "TEST")

    assert result.losses > 0
    assert result.max_drawdown_pct > 0.0
    assert result.total_trades == result.wins + result.losses


def test_position_still_open_at_data_end_is_force_closed():
    # Entry happens near the end of the series -- not enough remaining
    # bars to hit a stop or target before the data runs out.
    prices = [100 + i * 1.5 for i in range(35)]
    result = run_backtest(_candles(prices), "TEST")

    assert result.total_trades >= 1
    assert all(trade.exit_reason is not None for trade in result.trades)  # nothing left dangling OPEN
    assert result.trades[-1].exit_reason == ExitReason.MANUAL


def test_every_closed_trade_carries_strategy_attribution():
    prices = [100 + i * 1.5 for i in range(120)]
    result = run_backtest(_candles(prices), "TEST")
    assert all(trade.strategy == "TREND_FOLLOWING" for trade in result.trades)


def test_custom_starting_capital_is_reflected_in_result():
    result = run_backtest(_candles([100.0] * 60), "TEST", initial_capital_inr=10_000.0, protected_floor_inr=10_000.0)
    assert result.starting_capital_inr == 10_000.0
    assert result.ending_tradable_capital_inr == pytest.approx(10_000.0)


def test_no_open_positions_left_after_a_backtest_completes():
    prices = [100 + i * 1.5 for i in range(120)]
    result = run_backtest(_candles(prices), "TEST")
    # every trade in the result is CLOSED -- checked indirectly since
    # PaperPosition doesn't expose the engine, but realized_pnl() raises
    # on anything still open, so this would fail loudly if one leaked through.
    for trade in result.trades:
        trade.realized_pnl()
