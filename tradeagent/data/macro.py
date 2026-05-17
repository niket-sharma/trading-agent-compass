"""FRED and yfinance macro data client.

Fetches macro time series (DGS10, DGS2, UNRATE, CPIAUCSL, VIX) and saves
them to data/macro/ via the store module.
"""

from __future__ import annotations

from datetime import date

import httpx
import pandas as pd
import structlog
import yfinance as yf
from tenacity import retry, stop_after_attempt, wait_exponential

from tradeagent.secrets import get_secret

log = structlog.get_logger(__name__)

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"

# Series fetched by fetch_common_macro()
COMMON_SERIES = {
    "DGS10": "10-Year Treasury Constant Maturity Rate",
    "DGS2": "2-Year Treasury Constant Maturity Rate",
    "UNRATE": "Unemployment Rate",
    "CPIAUCSL": "Consumer Price Index for All Urban Consumers",
}


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def fetch_fred_series(
    series_id: str,
    start: date,
    end: date | None = None,
) -> pd.DataFrame:
    """Fetch a FRED time series.

    Args:
        series_id: FRED series identifier (e.g. "DGS10").
        start: Start date (inclusive).
        end: End date (inclusive). Defaults to today.

    Returns:
        DataFrame with columns [date, value]. date is datetime64[ns, UTC].
        Returns empty DataFrame on failure or missing API key.
    """
    api_key = get_secret("FRED_API_KEY", allow_session=False)
    if not api_key:
        log.warning("FRED_API_KEY not set — skipping FRED fetch", series=series_id)
        return pd.DataFrame(columns=["date", "value"])

    params: dict[str, str] = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "observation_start": start.isoformat(),
        "realtime_start": "latest",
        "realtime_end": "latest",
    }
    if end:
        params["observation_end"] = end.isoformat()

    try:
        resp = httpx.get(FRED_BASE, params=params, timeout=15.0)
        resp.raise_for_status()
        obs = resp.json().get("observations", [])
        if not obs:
            return pd.DataFrame(columns=["date", "value"])

        rows = [
            {"date": o["date"], "value": float(o["value"]) if o["value"] != "." else float("nan")}
            for o in obs
        ]
        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"], utc=True)
        df = df.dropna(subset=["value"]).sort_values("date").reset_index(drop=True)

        log.info("fetched FRED series", series=series_id, rows=len(df))
        return df

    except Exception as exc:
        log.error("failed to fetch FRED series", series=series_id, error=str(exc))
        return pd.DataFrame(columns=["date", "value"])


def fetch_vix(start: date, end: date | None = None) -> pd.DataFrame:
    """Fetch VIX daily close from yfinance.

    Returns:
        DataFrame with columns [date, value]. date is datetime64[ns, UTC].
    """
    try:
        raw = yf.download(
            "^VIX",
            start=start.isoformat(),
            end=end.isoformat() if end else None,
            auto_adjust=False,
            progress=False,
        )
        if raw.empty:
            return pd.DataFrame(columns=["date", "value"])
        df = raw[["Close"]].reset_index()
        df.columns = ["date", "value"]
        df["date"] = pd.to_datetime(df["date"], utc=True)
        df = df.dropna(subset=["value"]).sort_values("date").reset_index(drop=True)
        log.info("fetched VIX", rows=len(df))
        return df
    except Exception as exc:
        log.error("failed to fetch VIX", error=str(exc))
        return pd.DataFrame(columns=["date", "value"])


def fetch_common_macro(start: date) -> dict[str, pd.DataFrame]:
    """Fetch all standard macro series.

    Returns:
        dict mapping series_id → DataFrame [date, value].
        "VIX" key is included (sourced from yfinance, not FRED).
    """
    result: dict[str, pd.DataFrame] = {}
    for series_id in COMMON_SERIES:
        result[series_id] = fetch_fred_series(series_id, start)
    result["VIX"] = fetch_vix(start)
    return result
