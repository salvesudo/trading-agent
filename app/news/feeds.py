"""
Known RSS feed sources -- Phase 8.

Every URL below was checked reachable (HTTP 200) and confirmed to be
standard RSS 2.0 from this environment on 2026-08-25 -- not assumed.
Feed URLs and structures are controlled entirely by the publisher and
can change or go away without notice; this list is only as accurate as
its last verification.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FeedSource:
    name: str
    url: str


FEEDS = [
    FeedSource("Moneycontrol", "https://www.moneycontrol.com/rss/marketreports.xml"),
    FeedSource("Economic Times", "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"),
    FeedSource("LiveMint", "https://www.livemint.com/rss/markets"),
    FeedSource("Business Standard", "https://www.business-standard.com/rss/markets-106.rss"),
]

__all__ = ["FeedSource", "FEEDS"]
