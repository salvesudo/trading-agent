import datetime as dt

import pytest

from app.news.aggregator import fetch_all, filter_by_keyword, score_all
from app.news.feeds import FeedSource
from app.news.models import NewsItem
from app.news.sentiment import Sentiment


class FakeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


class RaisingResponse:
    def raise_for_status(self):
        raise RuntimeError("simulated network failure")


class FakeHttpClient:
    """Maps URL -> response (or an object whose raise_for_status() blows up)."""

    def __init__(self, responses: dict):
        self.responses = responses

    def get(self, url, headers=None, timeout=None):
        return self.responses[url]


def _rss(items_xml: str) -> str:
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>T</title>{items_xml}</channel></rss>'


def _item_xml(title, link, pub_date):
    return f"<item><title>{title}</title><link>{link}</link><pubDate>{pub_date}</pubDate></item>"


def test_fetch_all_merges_and_sorts_newest_first():
    sources = [
        FeedSource("A", "https://a.example/feed.xml"),
        FeedSource("B", "https://b.example/feed.xml"),
    ]
    responses = {
        "https://a.example/feed.xml": FakeResponse(
            _rss(_item_xml("Older from A", "https://a.example/1", "Mon, 01 Jan 2024 09:00:00 +0530"))
        ),
        "https://b.example/feed.xml": FakeResponse(
            _rss(_item_xml("Newer from B", "https://b.example/1", "Tue, 02 Jan 2024 09:00:00 +0530"))
        ),
    }
    client = FakeHttpClient(responses)

    items = fetch_all(sources=sources, http_client=client)
    assert [i.title for i in items] == ["Newer from B", "Older from A"]


def test_fetch_all_skips_a_failing_source_without_raising():
    sources = [
        FeedSource("Good", "https://good.example/feed.xml"),
        FeedSource("Bad", "https://bad.example/feed.xml"),
    ]
    responses = {
        "https://good.example/feed.xml": FakeResponse(
            _rss(_item_xml("Working headline", "https://good.example/1", "Mon, 01 Jan 2024 09:00:00 +0530"))
        ),
        "https://bad.example/feed.xml": RaisingResponse(),
    }
    client = FakeHttpClient(responses)

    items = fetch_all(sources=sources, http_client=client)
    assert len(items) == 1
    assert items[0].title == "Working headline"


def test_fetch_all_items_without_pubdate_sort_last():
    sources = [FeedSource("A", "https://a.example/feed.xml")]
    xml = _rss(
        _item_xml("Dated", "https://a.example/1", "Mon, 01 Jan 2024 09:00:00 +0530")
        + "<item><title>Undated</title><link>https://a.example/2</link></item>"
    )
    client = FakeHttpClient({"https://a.example/feed.xml": FakeResponse(xml)})

    items = fetch_all(sources=sources, http_client=client)
    assert items[0].title == "Dated"
    assert items[-1].title == "Undated"


def _news_item(title, summary="", source="Test"):
    return NewsItem(
        title=title, link=f"https://example.com/{title}",
        published_at=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc),
        summary=summary, source=source,
    )


def test_filter_by_keyword_matches_title_case_insensitively():
    items = [_news_item("RELIANCE shares gain"), _news_item("TCS reports earnings")]
    filtered = filter_by_keyword(items, "reliance")
    assert len(filtered) == 1
    assert filtered[0].title == "RELIANCE shares gain"


def test_filter_by_keyword_matches_summary_too():
    items = [_news_item("Market update", summary="Reliance Industries leads gainers")]
    filtered = filter_by_keyword(items, "Reliance")
    assert len(filtered) == 1


def test_filter_by_keyword_no_match_returns_empty():
    items = [_news_item("TCS reports earnings")]
    assert filter_by_keyword(items, "Reliance") == []


def test_score_all_pairs_each_item_with_its_sentiment():
    items = [_news_item("Market crashes on weak cues"), _news_item("Stock rallies to record high")]
    scored = score_all(items)
    assert len(scored) == 2
    assert scored[0].sentiment.sentiment == Sentiment.NEGATIVE
    assert scored[1].sentiment.sentiment == Sentiment.POSITIVE
