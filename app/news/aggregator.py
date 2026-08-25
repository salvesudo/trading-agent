"""
News aggregation -- Phase 8.

Ties feed fetching (app/news/rss_client.py) and sentiment scoring
(app/news/sentiment.py) together, plus simple keyword-based relevance
filtering. This is the entry point later phases (Strategy Engine, Phase
9) are expected to use rather than importing rss_client/sentiment
directly.

Advisory only, same as every analysis-layer module in this project:
nothing here decides whether to trade (spec section 47).
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import List, Optional

from app.news.feeds import FEEDS, FeedSource
from app.news.models import NewsItem
from app.news.rss_client import SupportsGet, fetch_feed
from app.news.sentiment import SentimentScore, score_news_item

_EPOCH = dt.datetime(1970, 1, 1, tzinfo=dt.timezone.utc)


@dataclass(frozen=True)
class ScoredNewsItem:
    item: NewsItem
    sentiment: SentimentScore


def fetch_all(
    sources: Optional[List[FeedSource]] = None, http_client: Optional[SupportsGet] = None
) -> List[NewsItem]:
    """Fetch every known feed, merged and sorted newest-first. A single
    source failing (network error, bad XML) is skipped rather than
    failing the whole batch -- one unreachable publisher shouldn't block
    the rest. Items with no parseable pubDate sort last."""
    items: List[NewsItem] = []
    for source in sources or FEEDS:
        try:
            items.extend(fetch_feed(source, http_client=http_client))
        except Exception:  # noqa: BLE001 -- one bad source shouldn't sink the batch
            continue
    items.sort(key=lambda i: i.published_at or _EPOCH, reverse=True)
    return items


def filter_by_keyword(items: List[NewsItem], keyword: str) -> List[NewsItem]:
    """Simple case-insensitive substring match against title + summary.
    No NER, no fuzzy matching -- a headline referring to a company by a
    name/spelling not in `keyword` won't match. A reasonable first
    filter, not a claim of completeness."""
    needle = keyword.lower()
    return [i for i in items if needle in i.title.lower() or needle in i.summary.lower()]


def score_all(items: List[NewsItem]) -> List[ScoredNewsItem]:
    return [ScoredNewsItem(item=i, sentiment=score_news_item(i)) for i in items]


__all__ = ["ScoredNewsItem", "fetch_all", "filter_by_keyword", "score_all"]
