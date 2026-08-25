import datetime as dt

from app.news.models import NewsItem
from app.news.sentiment import Sentiment, score_news_item, score_text


def test_neutral_when_no_keywords_match():
    result = score_text("The market opened as expected today.")
    assert result.sentiment == Sentiment.NEUTRAL
    assert result.score == 0.0


def test_positive_headline():
    result = score_text("Sensex, Nifty rally to record high on strong earnings; Nifty gains 2%")
    assert result.sentiment == Sentiment.POSITIVE
    assert result.score > 0
    assert result.positive_hits > result.negative_hits


def test_negative_headline():
    result = score_text("Sensex crashes, Nifty plunges as selloff deepens on recession fears")
    assert result.sentiment == Sentiment.NEGATIVE
    assert result.score < 0


def test_mixed_headline_nets_out():
    # 2 positive (surge, gain) vs 1 negative (fall) -> net positive
    result = score_text("Stock surges after early fall, ends session with strong gain")
    assert result.positive_hits == 2
    assert result.negative_hits == 1
    assert result.sentiment == Sentiment.POSITIVE


def test_case_insensitive_matching():
    upper = score_text("MARKET CRASHES ON WEAK GLOBAL CUES")
    lower = score_text("market crashes on weak global cues")
    assert upper.negative_hits == lower.negative_hits > 0


def test_word_boundary_avoids_false_substring_matches():
    # "gains" should match; "against" should not match "gain" as a substring.
    result = score_text("Company reported strong gains against expectations")
    assert result.positive_hits == 1


def test_score_news_item_combines_title_and_summary():
    item = NewsItem(
        title="Market update",
        link="https://example.com/1",
        published_at=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc),
        summary="Shares plunge on weak guidance",
        source="Test",
    )
    result = score_news_item(item)
    assert result.sentiment == Sentiment.NEGATIVE
