"""
RSS feed fetch/parse -- Phase 8.

Deliberately hand-rolled with stdlib `xml.etree.ElementTree` rather than
a third-party feed-parsing library: every feed this project uses (see
app/news/feeds.py) was checked to be standard RSS 2.0 -- title/link/
description/pubDate/guid, pubDate in RFC-822 format -- before writing
this, not assumed. If a future feed needs broader format tolerance
(Atom, unusual date formats), that's a reason to reconsider this
trade-off then, not to pull in a general-purpose parser up front for
cases that don't exist yet in this project's actual feed list.

Business Standard's feed returns HTTP 403 without a browser-like
User-Agent header (checked directly); the others don't need one but
accept it fine, so every request sends one.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from typing import List, Optional, Protocol

from app.news.feeds import FeedSource
from app.news.models import NewsItem

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


class _ResponseLike(Protocol):
    text: str

    def raise_for_status(self) -> None: ...


class SupportsGet(Protocol):
    def get(self, url: str, headers: dict, timeout: float) -> _ResponseLike: ...


def _parse_pubdate(raw: Optional[str]):
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError):
        return None


def parse_rss(xml_text: str, source_name: str) -> List[NewsItem]:
    """Parse a standard RSS 2.0 document into NewsItems. Skips any
    <item> missing a title or link rather than raising -- one malformed
    entry in a feed shouldn't take down the whole fetch. ElementTree
    handles CDATA-wrapped fields transparently (several of these feeds
    use it), so no special-casing needed for that."""
    root = ET.fromstring(xml_text)
    items: List[NewsItem] = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if not title or not link:
            continue
        items.append(
            NewsItem(
                title=title,
                link=link,
                published_at=_parse_pubdate(item.findtext("pubDate")),
                summary=(item.findtext("description") or "").strip(),
                source=source_name,
            )
        )
    return items


def fetch_feed(source: FeedSource, http_client: Optional[SupportsGet] = None) -> List[NewsItem]:
    if http_client is None:
        import httpx

        http_client = httpx.Client()
    response = http_client.get(source.url, headers={"User-Agent": USER_AGENT}, timeout=10.0)
    response.raise_for_status()
    return parse_rss(response.text, source.name)


__all__ = ["USER_AGENT", "SupportsGet", "parse_rss", "fetch_feed"]
