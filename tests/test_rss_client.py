import datetime as dt

import pytest

from app.news.feeds import FeedSource
from app.news.rss_client import fetch_feed, parse_rss

# Faithful to the real, live-verified structure of each feed (checked
# directly against https://www.moneycontrol.com/rss/marketreports.xml,
# economictimes.indiatimes.com's markets feed, livemint.com/rss/markets,
# and business-standard.com/rss/markets-106.rss on 2026-08-25) -- not
# invented from scratch.

MONEYCONTROL_STYLE_XML = """<?xml version="1.0" encoding="ISO-8859-1" ?>
<rss version="2.0">
<channel>
<title>Moneycontrol Market Reports</title>
<link>https://www.moneycontrol.com</link>
<item>
<title>Taking Stock: Market fails to hold on to day's gains, ends marginally higher</title>
<link>https://www.moneycontrol.com/news/local-markets/taking-stock-123.html</link>
<description>&lt;img src="x.jpg"/&gt; Grasim Industries, Bharti Airtel were the biggest gainers</description>
<pubDate>Tue, 23 Apr 2024 15:46:31 +0530</pubDate>
<guid>https://www.moneycontrol.com/news/local-markets/taking-stock-123.html</guid>
</item>
</channel>
</rss>
"""

CDATA_STYLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss xmlns:atom="http://www.w3.org/2005/Atom" version="2.0">
<channel>
<title>Markets-Economic Times</title>
<item>
<title><![CDATA[Block deal alert! Ribbit Capital to likely offload 1.6% stake in Groww]]></title>
<description><![CDATA[Groww may see a block deal as investor Ribbit Capital plans to sell.]]></description>
<link>https://economictimes.indiatimes.com/markets/stocks/news/block-deal-alert.cms</link>
<guid>https://economictimes.indiatimes.com/markets/stocks/news/block-deal-alert.cms</guid>
<pubDate>Tue, 25 Aug 2026 18:05:15 +0530</pubDate>
</item>
</channel>
</rss>
"""

MALFORMED_ITEM_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
<title>Test Feed</title>
<item>
<title>Has a title but no link</title>
<description>Should be skipped</description>
</item>
<item>
<title>Valid Item</title>
<link>https://example.com/valid</link>
<pubDate>not a real date</pubDate>
</item>
</channel>
</rss>
"""


def test_parse_rss_plain_text_fields():
    items = parse_rss(MONEYCONTROL_STYLE_XML, "Moneycontrol")
    assert len(items) == 1
    item = items[0]
    assert item.title == "Taking Stock: Market fails to hold on to day's gains, ends marginally higher"
    assert item.link == "https://www.moneycontrol.com/news/local-markets/taking-stock-123.html"
    assert item.source == "Moneycontrol"
    assert item.published_at == dt.datetime(2024, 4, 23, 15, 46, 31, tzinfo=dt.timezone(dt.timedelta(hours=5, minutes=30)))


def test_parse_rss_cdata_wrapped_fields():
    items = parse_rss(CDATA_STYLE_XML, "Economic Times")
    assert len(items) == 1
    item = items[0]
    assert "Ribbit Capital" in item.title
    assert "block deal" in item.summary
    assert item.source == "Economic Times"


def test_parse_rss_skips_item_missing_link():
    items = parse_rss(MALFORMED_ITEM_XML, "Test Feed")
    assert len(items) == 1
    assert items[0].title == "Valid Item"


def test_parse_rss_unparseable_pubdate_becomes_none():
    items = parse_rss(MALFORMED_ITEM_XML, "Test Feed")
    assert items[0].published_at is None


def test_parse_rss_empty_channel_returns_empty_list():
    xml = '<?xml version="1.0"?><rss version="2.0"><channel><title>Empty</title></channel></rss>'
    assert parse_rss(xml, "Empty") == []


def test_parse_rss_raises_on_genuinely_malformed_xml():
    with pytest.raises(Exception):
        parse_rss("<rss><channel><item><title>unterminated", "Bad Feed")


class FakeResponse:
    def __init__(self, text, status_ok=True):
        self.text = text
        self._status_ok = status_ok

    def raise_for_status(self):
        if not self._status_ok:
            raise RuntimeError("HTTP error")


class FakeHttpClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def get(self, url, headers=None, timeout=None):
        self.calls.append((url, headers, timeout))
        return self.response


def test_fetch_feed_sends_user_agent_header():
    client = FakeHttpClient(FakeResponse(MONEYCONTROL_STYLE_XML))
    source = FeedSource("Moneycontrol", "https://example.com/feed.xml")
    items = fetch_feed(source, http_client=client)

    assert len(items) == 1
    url, headers, timeout = client.calls[0]
    assert url == "https://example.com/feed.xml"
    assert "User-Agent" in headers


def test_fetch_feed_raises_on_http_error():
    client = FakeHttpClient(FakeResponse("", status_ok=False))
    source = FeedSource("Broken", "https://example.com/broken.xml")
    with pytest.raises(RuntimeError):
        fetch_feed(source, http_client=client)
