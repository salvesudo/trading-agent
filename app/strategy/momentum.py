"""
Momentum strategy -- Phase 9.

Simple, explicit rule: RSI crossing the 50 midline in the direction of
rising/falling MACD histogram momentum. Deliberately not gated on
regime -- momentum bursts can happen inside a RANGING regime too,
unlike trend.py, which requires a classified trend.
"""
from __future__ import annotations

from typing import Optional

from app.analysis import indicators
from app.analysis.indicators import InsufficientDataError
from app.strategy.models import StrategyContext, StrategyName, StrategySignal
from app.strategy.sizing import atr_stop_and_target

RSI_WINDOW = 14
ATR_WINDOW = 14
STOP_MULTIPLE = 1.5
REWARD_MULTIPLE = 1.5


def generate(context: StrategyContext) -> Optional[StrategySignal]:
    try:
        rsi_values = indicators.rsi(context.candles, window=RSI_WINDOW)
        macd_result = indicators.macd(context.candles)
        atr_values = indicators.atr(context.candles, window=ATR_WINDOW)
    except InsufficientDataError:
        return None

    if len(rsi_values) < 2 or len(macd_result.histogram) < 2:
        return None

    prev_rsi, latest_rsi = rsi_values[-2], rsi_values[-1]
    prev_hist, latest_hist = macd_result.histogram[-2], macd_result.histogram[-1]
    close = context.candles[-1].close
    latest_atr = atr_values[-1]

    crossed_up = prev_rsi <= 50.0 < latest_rsi
    crossed_down = prev_rsi >= 50.0 > latest_rsi
    momentum_rising = latest_hist > prev_hist
    momentum_falling = latest_hist < prev_hist

    if crossed_up and momentum_rising and latest_hist > 0:
        side = "BUY"
    elif crossed_down and momentum_falling and latest_hist < 0:
        side = "SELL"
    else:
        return None

    stop, target = atr_stop_and_target(close, latest_atr, side, STOP_MULTIPLE, REWARD_MULTIPLE)
    confidence = min(1.0, abs(latest_rsi - 50.0) / 30.0)
    return StrategySignal(
        strategy=StrategyName.MOMENTUM,
        symbol=context.symbol,
        side=side,
        entry_price=close,
        stop_loss=stop,
        target=target,
        confidence=confidence,
        reason=(
            f"RSI{RSI_WINDOW} crossed {'above' if side == 'BUY' else 'below'} 50 "
            f"({prev_rsi:.1f}->{latest_rsi:.1f}), MACD histogram "
            f"{'rising' if side == 'BUY' else 'falling'} ({prev_hist:.3f}->{latest_hist:.3f})."
        ),
    )


__all__ = ["generate"]
