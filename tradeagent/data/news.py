"""Tiingo News client — cached-news architecture.

Fetches news articles into data/news/{TICKER}.parquet. Called by the CLI and
GitHub Actions, never by the Streamlit app at request time.

The cached-news architecture: articles are pre-fetched and committed to the repo.
Sentiment scoring runs on-demand in the Streamlit app against these cached articles
using the visitor's own OpenAI key.
"""

from __future__ import annotations

import hashlib
import time
from datetime import UTC, datetime, timedelta

import httpx
import pandas as pd
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from tradeagent.secrets import get_secret

log = structlog.get_logger(__name__)

TIINGO_NEWS_BASE = "https://api.tiingo.com/tiingo/news"


def _article_hash(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def fetch_articles(
    ticker: str,
    days: int = 7,
) -> pd.DataFrame:
    """Fetch recent news articles for a ticker from Tiingo News.

    Args:
        ticker: Ticker symbol (e.g. "QQQ").
        days: Fetch articles published within the last N days.

    Returns:
        DataFrame with columns [id, ticker, published_at, title, url, source, body, hash].
        published_at is datetime64[ns, UTC]. Returns empty DataFrame on failure.
    """
    api_key = get_secret("TIINGO_API_KEY", allow_session=False)
    if not api_key:
        log.warning("TIINGO_API_KEY not set — skipping news fetch", ticker=ticker)
        return pd.DataFrame(
            columns=["id", "ticker", "published_at", "title", "url", "source", "body", "hash"]
        )

    start_date = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%d")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Token {api_key}",
    }
    params = {
        "tickers": ticker.upper(),
        "startDate": start_date,
        "limit": 100,
        "sortBy": "publishedDate",
    }

    t0 = time.monotonic()
    try:
        resp = httpx.get(TIINGO_NEWS_BASE, headers=headers, params=params, timeout=15.0)
        resp.raise_for_status()
        articles = resp.json()

        if not articles:
            log.info("no news articles found", ticker=ticker, days=days)
            return pd.DataFrame(
                columns=["id", "ticker", "published_at", "title", "url", "source", "body", "hash"]
            )

        rows = []
        for art in articles:
            url = art.get("url", "")
            rows.append(
                {
                    "id": str(art.get("id", "")),
                    "ticker": ticker.upper(),
                    "published_at": pd.Timestamp(art.get("publishedDate", ""), tz="UTC"),
                    "title": art.get("title", ""),
                    "url": url,
                    "source": art.get("source", ""),
                    "body": art.get("description", "") or art.get("body", ""),
                    "hash": _article_hash(url),
                }
            )

        df = pd.DataFrame(rows)
        df["published_at"] = pd.to_datetime(df["published_at"], utc=True)

        elapsed = time.monotonic() - t0
        log.info(
            "fetched news articles",
            ticker=ticker,
            count=len(df),
            days=days,
            duration_ms=round(elapsed * 1000),
        )
        return df

    except Exception as exc:
        log.error("failed to fetch news", ticker=ticker, error=str(exc))
        return pd.DataFrame(
            columns=["id", "ticker", "published_at", "title", "url", "source", "body", "hash"]
        )
