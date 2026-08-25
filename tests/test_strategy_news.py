import datetime as dt
from datetime import datetime, timedelta, timezone

from app.data.models import Candle
from app.news.models import NewsItem
from app.regime.detector import RegimeSnapshot, TrendState, VolatilityState
from app.strategy import news
from app.strategy.models import StrategyContext

_PLACEHOLDER_REGIME = RegimeSnapshot(
    trend=TrendState.RANGING, volatility=VolatilityState.NORMAL,
    adx=15.0, plus_di=15.0, minus_di=15.0, atr_pct=1.0, atr_pct_percentile=50.0,
)


def _candles(n=20, price=100.0):
    start = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
    return [
        Candle(timestamp=start + timedelta(minutes=i), open=price, high=price + 1, low=price - 1,
               close=price, volume=1000)
        for i in range(n)
    ]


def _news_item(title):
    return NewsItem(
        title=title, link=f"https://example.com/{hash(title)}",
        published_at=dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc), summary="", source="Test",
    )


def _context(items, candles=None):
    return StrategyContext(symbol="TEST", candles=candles or _candles(), regime=_PLACEHOLDER_REGIME, news_items=items)


def test_strongly_positive_news_generates_buy():
    items = [
        _news_item("Stock surges to record high on strong earnings beat"),
        _news_item("Shares rally as profit growth outperforms expectations"),
        _news_item("Company gains after upgrade, bullish outlook boosted"),
    ]
    signal = news.generate(_context(items))
    assert signal is not None
    assert signal.side == "BUY"
    assert signal.stop_loss < signal.entry_price < signal.target


def test_strongly_negative_news_generates_sell():
    items = [
        _news_item("Stock crashes after weak guidance, shares plunge"),
        _news_item("Company slumps on downgrade, bearish outlook weighs"),
        _news_item("Shares fall sharply as losses widen amid selloff"),
    ]
    signal = news.generate(_context(items))
    assert signal is not None
    assert signal.side == "SELL"
    assert signal.target < signal.entry_price < signal.stop_loss


def test_fewer_than_minimum_items_produces_no_signal():
    items = [
        _news_item("Stock surges to record high"),
        _news_item("Shares rally on strong earnings"),
    ]
    assert news.generate(_context(items)) is None


def test_mixed_neutral_sentiment_produces_no_signal():
    items = [
        _news_item("Stock surges to record high"),
        _news_item("Shares crash on weak guidance"),
        _news_item("Market update: trading unchanged today"),
    ]
    assert news.generate(_context(items)) is None


def test_no_news_items_produces_no_signal():
    assert news.generate(_context([])) is None


def test_insufficient_candle_data_produces_no_signal_not_an_exception():
    items = [
        _news_item("Stock surges to record high"),
        _news_item("Shares rally on strong earnings"),
        _news_item("Company gains after upgrade"),
    ]
    signal = news.generate(_context(items, candles=_candles(n=3)))
    assert signal is None
