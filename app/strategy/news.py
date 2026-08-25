"""
News-driven strategy -- Phase 9.

Trades in the direction of aggregate sentiment across recent news items
for this symbol (app.news.sentiment's lexicon-based scorer -- see that
module's docstring on accuracy limits before trusting this). Requires a
minimum number of scored items and a clearly one-sided aggregate before
firing at all, specifically so a single noisy headline can't be enough
to propose a trade on its own.
"""
from __future__ import annotations

from typing import Optional

from app.analysis import indicators
from app.analysis.indicators import InsufficientDataError
from app.news.sentiment import Sentiment, score_news_item
from app.strategy.models import StrategyContext, StrategyName, StrategySignal
from app.strategy.sizing import atr_stop_and_target

ATR_WINDOW = 14
MIN_ITEMS = 3
MIN_AVG_SCORE = 0.3  # aggregate must lean clearly one way, not just barely
STOP_MULTIPLE = 2.0  # news-driven moves are volatile; wider stop than the other strategies
REWARD_MULTIPLE = 1.5


def generate(context: StrategyContext) -> Optional[StrategySignal]:
    if len(context.news_items) < MIN_ITEMS:
        return None
    try:
        atr_values = indicators.atr(context.candles, window=ATR_WINDOW)
    except InsufficientDataError:
        return None

    scores = [score_news_item(item) for item in context.news_items]
    avg_score = sum(s.score for s in scores) / len(scores)
    if avg_score >= MIN_AVG_SCORE:
        side = "BUY"
    elif avg_score <= -MIN_AVG_SCORE:
        side = "SELL"
    else:
        return None

    close = context.candles[-1].close
    latest_atr = atr_values[-1]
    stop, target = atr_stop_and_target(close, latest_atr, side, STOP_MULTIPLE, REWARD_MULTIPLE)

    positive = sum(1 for s in scores if s.sentiment == Sentiment.POSITIVE)
    negative = sum(1 for s in scores if s.sentiment == Sentiment.NEGATIVE)
    return StrategySignal(
        strategy=StrategyName.NEWS,
        symbol=context.symbol,
        side=side,
        entry_price=close,
        stop_loss=stop,
        target=target,
        # Deliberately capped lower than the other strategies' max --
        # this rests on a keyword heuristic, not a validated model.
        confidence=min(0.6, abs(avg_score)),
        reason=(
            f"{len(context.news_items)} recent items, avg sentiment {avg_score:+.2f} "
            f"({positive} positive / {negative} negative), lexicon-based (see app/news/sentiment.py)."
        ),
    )


__all__ = ["generate"]
