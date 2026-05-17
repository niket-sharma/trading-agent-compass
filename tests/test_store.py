"""Tests for tradeagent.data.store."""

from __future__ import annotations

import hashlib
from datetime import date, timedelta

import pandas as pd


def test_save_and_load_prices(tmp_data_dir, sample_price_df):
    from tradeagent.data.store import load_prices, save_prices

    save_prices("QQQ", sample_price_df)
    loaded = load_prices("QQQ")

    assert not loaded.empty
    assert list(loaded.columns) == ["date", "open", "high", "low", "close", "adj_close", "volume"]
    assert len(loaded) == len(sample_price_df)


def test_load_prices_returns_empty_when_missing(tmp_data_dir):
    from tradeagent.data.store import load_prices

    df = load_prices("NONEXISTENT")
    assert df.empty


def test_save_prices_deduplicates(tmp_data_dir, sample_price_df):
    from tradeagent.data.store import load_prices, save_prices

    save_prices("QQQ", sample_price_df)
    save_prices("QQQ", sample_price_df)  # duplicate — should not double rows
    loaded = load_prices("QQQ")
    assert len(loaded) == len(sample_price_df)


def test_save_prices_date_filter(tmp_data_dir, sample_price_df):
    from tradeagent.data.store import load_prices, save_prices

    save_prices("QQQ", sample_price_df)
    start = date.today() - timedelta(days=2)
    loaded = load_prices("QQQ", start=start)
    assert len(loaded) <= len(sample_price_df)


def test_get_last_date(tmp_data_dir, sample_price_df):
    from tradeagent.data.store import get_last_date, save_prices

    save_prices("QQQ", sample_price_df)
    last = get_last_date("QQQ")
    assert last is not None
    assert last == date.today()


def test_get_last_date_missing(tmp_data_dir):
    from tradeagent.data.store import get_last_date

    assert get_last_date("NONEXISTENT") is None


def test_get_latest_data_date(tmp_data_dir, sample_price_df):
    from tradeagent.data.store import get_latest_data_date, save_prices

    save_prices("QQQ", sample_price_df)
    latest = get_latest_data_date()
    assert latest == date.today()


def test_get_latest_data_date_no_data(tmp_data_dir):
    from tradeagent.data.store import get_latest_data_date

    # Sentinel date returned when no data exists
    result = get_latest_data_date()
    assert result == date(2000, 1, 1)


def test_list_available_tickers(tmp_data_dir, sample_price_df):
    from tradeagent.data.store import list_available_tickers, save_prices

    save_prices("QQQ", sample_price_df)
    save_prices("TQQQ", sample_price_df)
    tickers = list_available_tickers()
    assert "QQQ" in tickers
    assert "TQQQ" in tickers


def test_save_and_load_news(tmp_data_dir, sample_news_df):
    from tradeagent.data.store import load_news, save_news

    save_news("QQQ", sample_news_df)
    loaded = load_news("QQQ")
    assert not loaded.empty
    assert len(loaded) == len(sample_news_df)


def test_save_news_rolling_window(tmp_data_dir):
    """Articles older than rolling_window_days must be dropped."""
    from tradeagent.data.store import load_news, save_news

    old_url = "https://example.com/old"
    new_url = "https://example.com/new"

    df = pd.DataFrame(
        [
            {
                "id": "1",
                "ticker": "QQQ",
                "published_at": pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=100),
                "title": "Old article",
                "url": old_url,
                "source": "test",
                "body": "old",
                "hash": hashlib.sha256(old_url.encode()).hexdigest(),
            },
            {
                "id": "2",
                "ticker": "QQQ",
                "published_at": pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=1),
                "title": "New article",
                "url": new_url,
                "source": "test",
                "body": "new",
                "hash": hashlib.sha256(new_url.encode()).hexdigest(),
            },
        ]
    )
    save_news("QQQ", df, rolling_window_days=90)
    loaded = load_news("QQQ")

    # Old article should be dropped, new one kept
    assert len(loaded) == 1
    assert loaded.iloc[0]["url"] == new_url


def test_save_news_deduplicates(tmp_data_dir, sample_news_df):
    from tradeagent.data.store import load_news, save_news

    save_news("QQQ", sample_news_df)
    save_news("QQQ", sample_news_df)  # run twice — should not double
    loaded = load_news("QQQ")
    assert len(loaded) == len(sample_news_df)


def test_save_and_load_macro(tmp_data_dir):
    from tradeagent.data.store import load_macro, save_macro

    df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-01", "2024-01-02"], utc=True),
            "value": [4.5, 4.6],
        }
    )
    save_macro("DGS10", df)
    loaded = load_macro("DGS10")
    assert len(loaded) == 2
    assert list(loaded.columns) == ["date", "value"]
