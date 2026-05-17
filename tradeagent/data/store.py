"""Read/write helpers for static Parquet data files under data/.

All functions operate on the committed data/ directory (never at runtime from the
Streamlit app — data is pre-fetched by GitHub Actions and committed to the repo).

Parquet schemas (all dates are tz-aware UTC timestamps or date objects):

prices/{TICKER}.parquet
  date          datetime64[ns, UTC]  — trading day (market open date, NY)
  open          float64
  high          float64
  low           float64
  close         float64
  adj_close     float64
  volume        int64

fundamentals/{TICKER}.parquet
  ticker        object
  period_end    datetime64[ns, UTC]
  fiscal_period object   — e.g. "Q1 2024", "FY 2023"
  statement_type object  — "income", "balance_sheet", "cash_flow"
  metric        object   — e.g. "revenue", "net_income"
  value         float64

macro/{SERIES}.parquet
  date          datetime64[ns, UTC]
  value         float64

corporate_actions/{TICKER}.parquet
  ticker        object
  ex_date       datetime64[ns, UTC]
  type          object   — "dividend" | "split"
  ratio         float64  — split ratio (NaN for dividends)
  cash_amount   float64  — dividend amount (NaN for splits)

news/{TICKER}.parquet
  id            object   — Tiingo article ID
  ticker        object
  published_at  datetime64[ns, UTC]
  title         object
  url           object
  source        object
  body          object
  hash          object   — sha256(url), unique dedup key
"""

from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

import pandas as pd

_DATA_DIR = Path(__file__).parent.parent.parent / "data"


def _ticker_path(subdir: str, ticker: str) -> Path:
    return _DATA_DIR / subdir / f"{ticker.upper()}.parquet"


def _series_path(series_id: str) -> Path:
    return _DATA_DIR / "macro" / f"{series_id.upper()}.parquet"


# ──────────────────────────────────────────────
# Prices
# ──────────────────────────────────────────────


def load_prices(
    ticker: str,
    start: date | None = None,
    end: date | None = None,
) -> pd.DataFrame:
    """Load daily price bars for a ticker.

    Returns:
        DataFrame with columns [date, open, high, low, close, adj_close, volume].
        Index is a RangeIndex; 'date' column is datetime64[ns, UTC].
        Returns empty DataFrame if the file doesn't exist.
    """
    path = _ticker_path("prices", ticker)
    if not path.exists():
        return pd.DataFrame(
            columns=["date", "open", "high", "low", "close", "adj_close", "volume"]
        )
    df = pd.read_parquet(path)
    if start is not None:
        start_ts = pd.Timestamp(start, tz="UTC")
        df = df[df["date"] >= start_ts]
    if end is not None:
        end_ts = pd.Timestamp(end, tz="UTC")
        df = df[df["date"] <= end_ts]
    return df.reset_index(drop=True)


def save_prices(ticker: str, df: pd.DataFrame) -> None:
    """Save / overwrite daily price bars.

    Args:
        ticker: Ticker symbol.
        df: DataFrame with columns [date, open, high, low, close, adj_close, volume].
    """
    path = _ticker_path("prices", ticker)
    path.parent.mkdir(parents=True, exist_ok=True)
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"], utc=True)
    df = df.sort_values("date").drop_duplicates(subset="date")
    df.to_parquet(path, index=False)


# ──────────────────────────────────────────────
# Fundamentals
# ──────────────────────────────────────────────


def load_fundamentals(ticker: str) -> pd.DataFrame:
    """Load fundamental data in long format.

    Returns:
        DataFrame with columns [ticker, period_end, fiscal_period, statement_type, metric, value].
        Returns empty DataFrame if the file doesn't exist.
    """
    path = _ticker_path("fundamentals", ticker)
    if not path.exists():
        return pd.DataFrame(
            columns=["ticker", "period_end", "fiscal_period", "statement_type", "metric", "value"]
        )
    return pd.read_parquet(path)


def save_fundamentals(ticker: str, df: pd.DataFrame) -> None:
    path = _ticker_path("fundamentals", ticker)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)


# ──────────────────────────────────────────────
# Macro
# ──────────────────────────────────────────────


def load_macro(series_id: str) -> pd.DataFrame:
    """Load a macro time series.

    Returns:
        DataFrame with columns [date, value]. date is datetime64[ns, UTC].
        Returns empty DataFrame if file doesn't exist.
    """
    path = _series_path(series_id)
    if not path.exists():
        return pd.DataFrame(columns=["date", "value"])
    return pd.read_parquet(path)


def save_macro(series_id: str, df: pd.DataFrame) -> None:
    path = _series_path(series_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"], utc=True)
    df = df.sort_values("date").drop_duplicates(subset="date")
    df.to_parquet(path, index=False)


# ──────────────────────────────────────────────
# Corporate actions
# ──────────────────────────────────────────────


def load_corporate_actions(ticker: str) -> pd.DataFrame:
    """Load corporate actions (dividends + splits).

    Returns:
        DataFrame with columns [ticker, ex_date, type, ratio, cash_amount].
    """
    path = _ticker_path("corporate_actions", ticker)
    if not path.exists():
        return pd.DataFrame(
            columns=["ticker", "ex_date", "type", "ratio", "cash_amount"]
        )
    return pd.read_parquet(path)


def save_corporate_actions(ticker: str, df: pd.DataFrame) -> None:
    path = _ticker_path("corporate_actions", ticker)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)


# ──────────────────────────────────────────────
# News
# ──────────────────────────────────────────────


def load_news(ticker: str, days: int | None = None) -> pd.DataFrame:
    """Load cached news articles for a ticker.

    Args:
        ticker: Ticker symbol.
        days: If provided, return only articles published within the last N days.

    Returns:
        DataFrame with columns [id, ticker, published_at, title, url, source, body, hash].
        published_at is datetime64[ns, UTC]. Returns empty DataFrame if no data.
    """
    path = _ticker_path("news", ticker)
    if not path.exists():
        return pd.DataFrame(
            columns=["id", "ticker", "published_at", "title", "url", "source", "body", "hash"]
        )
    df = pd.read_parquet(path)
    if days is not None:
        cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=days)
        df = df[df["published_at"] >= cutoff]
    return df.reset_index(drop=True)


def save_news(
    ticker: str,
    new_df: pd.DataFrame,
    rolling_window_days: int = 90,
) -> None:
    """Upsert news articles and enforce the rolling window.

    Merges new_df with existing data, deduplicates by hash, drops articles
    older than rolling_window_days, and saves. Idempotent.

    Args:
        ticker: Ticker symbol.
        new_df: DataFrame with columns [id, ticker, published_at, title, url, source, body, hash].
        rolling_window_days: Drop articles older than this many days.
    """
    existing = load_news(ticker)
    combined = pd.concat([existing, new_df], ignore_index=True)

    # Compute hash from URL if missing
    if "hash" not in combined.columns or combined["hash"].isna().any():
        mask = combined["hash"].isna() if "hash" in combined.columns else slice(None)
        combined.loc[mask, "hash"] = combined.loc[mask, "url"].apply(
            lambda u: hashlib.sha256(str(u).encode()).hexdigest()
        )

    combined["published_at"] = pd.to_datetime(combined["published_at"], utc=True)
    cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=rolling_window_days)
    combined = (
        combined[combined["published_at"] >= cutoff]
        .drop_duplicates(subset="hash")
        .sort_values("published_at", ascending=False)
        .reset_index(drop=True)
    )

    path = _ticker_path("news", ticker)
    path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_parquet(path, index=False)


# ──────────────────────────────────────────────
# Utility
# ──────────────────────────────────────────────


def list_available_tickers() -> list[str]:
    """Return tickers that have a prices Parquet file."""
    prices_dir = _DATA_DIR / "prices"
    if not prices_dir.exists():
        return []
    return sorted(p.stem for p in prices_dir.glob("*.parquet"))


def get_last_date(ticker: str) -> date | None:
    """Return the most recent date in the prices file, or None if no data."""
    df = load_prices(ticker)
    if df.empty or "date" not in df.columns:
        return None
    return pd.Timestamp(df["date"].max()).date()


def get_latest_data_date() -> date:
    """Return max(date) across all price Parquet files. Used by the freshness banner.

    Returns:
        Most recent trading date present in data/prices/.
        Falls back to a far-past sentinel date if no data exists.
    """
    tickers = list_available_tickers()
    if not tickers:
        return date(2000, 1, 1)  # sentinel: triggers stale warning

    latest: date | None = None
    for ticker in tickers:
        d = get_last_date(ticker)
        if d is not None and (latest is None or d > latest):
            latest = d

    return latest if latest is not None else date(2000, 1, 1)


def url_hash(url: str) -> str:
    """Compute SHA-256 hash of a URL (article dedup key)."""
    return hashlib.sha256(url.encode()).hexdigest()
