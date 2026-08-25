"""
Lexicon-based sentiment scoring -- Phase 8.

Deliberately simple: counts occurrences of a small, curated list of
positive/negative financial-news keywords in a headline + summary. This
is a crude heuristic, not a trained NLP model or an LLM -- it will
misfire on sarcasm, negation ("shares fail to fall"), and any real
sentiment expressed in words that aren't on either list. It exists as an
honest, zero-dependency starting point, not a claim of accuracy.

Phase 13 (AI decision engine, advisory only -- spec section 47, it still
can't override the Risk Engine) is the natural place to replace or
augment this with an LLM-based score later; this module makes no attempt
to anticipate that and shouldn't be trusted as more than a rough signal
until it does.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from app.news.models import NewsItem

POSITIVE_WORDS = [
    "surge", "surges", "surged", "rally", "rallies", "rallied", "gain", "gains", "gained",
    "jump", "jumps", "jumped", "soar", "soars", "soared", "beat", "beats", "record high",
    "upgrade", "upgraded", "profit", "profits", "growth", "outperform", "bullish",
    "rebound", "rebounds", "recovery", "boost", "boosts", "boosted", "all-time high",
]

NEGATIVE_WORDS = [
    "crash", "crashes", "crashed", "plunge", "plunges", "plunged", "slump", "slumps",
    "slumped", "fall", "falls", "fell", "drop", "drops", "dropped", "loss", "losses",
    "downgrade", "downgraded", "selloff", "sell-off", "bearish", "recession", "fraud",
    "default", "miss", "misses", "missed", "decline", "declines", "declined", "record low",
]

_POSITIVE_PATTERN = re.compile(r"\b(" + "|".join(re.escape(w) for w in POSITIVE_WORDS) + r")\b", re.IGNORECASE)
_NEGATIVE_PATTERN = re.compile(r"\b(" + "|".join(re.escape(w) for w in NEGATIVE_WORDS) + r")\b", re.IGNORECASE)


class Sentiment(str, Enum):
    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    NEUTRAL = "NEUTRAL"


@dataclass(frozen=True)
class SentimentScore:
    sentiment: Sentiment
    score: float  # -1.0 (most negative) to +1.0 (most positive); 0.0 if no keywords matched
    positive_hits: int
    negative_hits: int


def score_text(text: str) -> SentimentScore:
    positive_hits = len(_POSITIVE_PATTERN.findall(text))
    negative_hits = len(_NEGATIVE_PATTERN.findall(text))
    total = positive_hits + negative_hits
    if total == 0:
        return SentimentScore(Sentiment.NEUTRAL, 0.0, 0, 0)
    score = (positive_hits - negative_hits) / total
    if score > 0:
        sentiment = Sentiment.POSITIVE
    elif score < 0:
        sentiment = Sentiment.NEGATIVE
    else:
        sentiment = Sentiment.NEUTRAL
    return SentimentScore(sentiment, score, positive_hits, negative_hits)


def score_news_item(item: NewsItem) -> SentimentScore:
    return score_text(f"{item.title} {item.summary}")


__all__ = ["Sentiment", "SentimentScore", "score_text", "score_news_item", "POSITIVE_WORDS", "NEGATIVE_WORDS"]
