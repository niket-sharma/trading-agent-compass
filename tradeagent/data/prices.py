"""yfinance wrapper for daily price bars, dividends, and splits.

These functions are called by the CLI / GitHub Actions, never by the Streamlit app
at request time. All results are written to data/prices/ via the store module.
"""

from __future__ import annotations

import time
from datetime import date

import pandas as pd
import structlog
import yfinance as yf
from tenacity import retry, stop_after_attempt, wait_exponential

log = structlog.get_logger(__name__)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def fetch_daily_bars(
    ticker: str,
    start: date,
    end: date | None = None,
) -> pd.DataFrame:
    """Fetch daily OHLCV bars from yfinance.

    Args:
        ticker: Ticker symbol (e.g. "QQQ").
        start: Start date (inclusive).
        end: End date (inclusive). Defaults to today.

    Returns:
        DataFrame with columns [date, open, high, low, close, adj_close, volume].
        date is datetime64[ns, UTC]. Returns empty DataFrame on failure.
    """
    t0 = time.monotonic()
    try:
        tkr = yf.Ticker(ticker)
        raw = tkr.history(
            start=start.isoformat(),
            end=end.isoformat() if end else None,
            auto_adjust=False,
            actions=False,
        )
        if raw.empty:
            log.warning("yfinance returned empty bars", ticker=ticker, start=str(start))
            return pd.DataFrame(
                columns=["date", "open", "high", "low", "close", "adj_close", "volume"]
            )

        df = raw.reset_index()
        # Normalize column names — yfinance uses capitalized names
        df.columns = [c.lower().replace(" ", "_") for c in df.columns]

        # yfinance may return 'close' and 'adj close' or 'adj_close'
        if "adj_close" not in df.columns and "adj close" in raw.columns:
            df["adj_close"] = raw["Adj Close"].values
        elif "adj_close" not in df.columns:
            df["adj_close"] = df["close"]

        df = df.rename(columns={"date": "date"})
        df["date"] = pd.to_datetime(df["date"], utc=True)

        # Keep only required columns
        cols = ["date", "open", "high", "low", "close", "adj_close", "volume"]
        for col in cols:
            if col not in df.columns:
                df[col] = float("nan")

        df = df[cols].copy()
        df["volume"] = df["volume"].fillna(0).astype("int64")
        for col in ["open", "high", "low", "close", "adj_close"]:
            df[col] = df[col].astype("float64")

        elapsed = time.monotonic() - t0
        log.info(
            "fetched daily bars",
            ticker=ticker,
            rows=len(df),
            start=str(start),
            end=str(df["date"].max().date()) if not df.empty else None,
            duration_ms=round(elapsed * 1000),
        )
        return df

    except Exception as exc:
        log.error("failed to fetch daily bars", ticker=ticker, error=str(exc))
        return pd.DataFrame(
            columns=["date", "open", "high", "low", "close", "adj_close", "volume"]
        )


def fetch_dividends(ticker: str) -> pd.DataFrame:
    """Fetch dividend history.

    Returns:
        DataFrame with columns [ticker, ex_date, cash_amount].
        ex_date is datetime64[ns, UTC].
    """
    try:
        tkr = yf.Ticker(ticker)
        divs = tkr.dividends
        if divs.empty:
            return pd.DataFrame(columns=["ticker", "ex_date", "cash_amount"])
        df = divs.reset_index()
        df.columns = ["ex_date", "cash_amount"]
        df["ticker"] = ticker.upper()
        df["ex_date"] = pd.to_datetime(df["ex_date"], utc=True)
        df["type"] = "dividend"
        df["ratio"] = float("nan")
        return df[["ticker", "ex_date", "type", "ratio", "cash_amount"]].copy()
    except Exception as exc:
        log.error("failed to fetch dividends", ticker=ticker, error=str(exc))
        return pd.DataFrame(columns=["ticker", "ex_date", "type", "ratio", "cash_amount"])


def fetch_splits(ticker: str) -> pd.DataFrame:
    """Fetch stock split history.

    Returns:
        DataFrame with columns [ticker, ex_date, type, ratio, cash_amount].
        ratio is the split factor (e.g. 4.0 for a 4:1 split).
    """
    try:
        tkr = yf.Ticker(ticker)
        splits = tkr.splits
        if splits.empty:
            return pd.DataFrame(columns=["ticker", "ex_date", "type", "ratio", "cash_amount"])
        df = splits.reset_index()
        df.columns = ["ex_date", "ratio"]
        df["ticker"] = ticker.upper()
        df["ex_date"] = pd.to_datetime(df["ex_date"], utc=True)
        df["type"] = "split"
        df["cash_amount"] = float("nan")
        return df[["ticker", "ex_date", "type", "ratio", "cash_amount"]].copy()
    except Exception as exc:
        log.error("failed to fetch splits", ticker=ticker, error=str(exc))
        return pd.DataFrame(columns=["ticker", "ex_date", "type", "ratio", "cash_amount"])
