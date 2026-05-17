"""yfinance wrapper for quarterly and annual fundamentals.

Returns data in a long (tidy) format suitable for Parquet storage.
"""

from __future__ import annotations

import pandas as pd
import structlog
import yfinance as yf

log = structlog.get_logger(__name__)


def _pivot_to_long(
    raw: pd.DataFrame,
    ticker: str,
    statement_type: str,
    fiscal_period_label: str,
) -> pd.DataFrame:
    """Convert a wide yfinance financial DataFrame to long format.

    Args:
        raw: yfinance DataFrame — columns are metric names, index is period end dates.
        ticker: Ticker symbol.
        statement_type: "income" | "balance_sheet" | "cash_flow".
        fiscal_period_label: "quarterly" | "annual".

    Returns:
        Long DataFrame [ticker, period_end, fiscal_period, statement_type, metric, value].
    """
    if raw is None or raw.empty:
        return pd.DataFrame(
            columns=["ticker", "period_end", "fiscal_period", "statement_type", "metric", "value"]
        )
    rows = []
    for period_end, row in raw.T.items():
        for metric, value in row.items():
            rows.append(
                {
                    "ticker": ticker.upper(),
                    "period_end": pd.Timestamp(period_end, tz="UTC"),
                    "fiscal_period": f"{fiscal_period_label} {pd.Timestamp(period_end).year}",
                    "statement_type": statement_type,
                    "metric": str(metric),
                    "value": float(value) if value is not None else float("nan"),
                }
            )
    return pd.DataFrame(rows)


def fetch_quarterly(ticker: str) -> pd.DataFrame:
    """Fetch quarterly income statement, balance sheet, and cash flow.

    Returns:
        Long DataFrame [ticker, period_end, fiscal_period, statement_type, metric, value].
        period_end is datetime64[ns, UTC].
    """
    try:
        tkr = yf.Ticker(ticker)
        frames = []
        for attr, label in [
            ("quarterly_income_stmt", "income"),
            ("quarterly_balance_sheet", "balance_sheet"),
            ("quarterly_cash_flow", "cash_flow"),
        ]:
            raw = getattr(tkr, attr, None)
            frames.append(_pivot_to_long(raw, ticker, label, "Q"))
        result = pd.concat([f for f in frames if not f.empty], ignore_index=True)
        log.info("fetched quarterly fundamentals", ticker=ticker, rows=len(result))
        return result
    except Exception as exc:
        log.error("failed to fetch quarterly fundamentals", ticker=ticker, error=str(exc))
        return pd.DataFrame(
            columns=["ticker", "period_end", "fiscal_period", "statement_type", "metric", "value"]
        )


def fetch_annual(ticker: str) -> pd.DataFrame:
    """Fetch annual income statement, balance sheet, and cash flow.

    Returns:
        Long DataFrame [ticker, period_end, fiscal_period, statement_type, metric, value].
    """
    try:
        tkr = yf.Ticker(ticker)
        frames = []
        for attr, label in [
            ("income_stmt", "income"),
            ("balance_sheet", "balance_sheet"),
            ("cash_flow", "cash_flow"),
        ]:
            raw = getattr(tkr, attr, None)
            frames.append(_pivot_to_long(raw, ticker, label, "FY"))
        result = pd.concat([f for f in frames if not f.empty], ignore_index=True)
        log.info("fetched annual fundamentals", ticker=ticker, rows=len(result))
        return result
    except Exception as exc:
        log.error("failed to fetch annual fundamentals", ticker=ticker, error=str(exc))
        return pd.DataFrame(
            columns=["ticker", "period_end", "fiscal_period", "statement_type", "metric", "value"]
        )
