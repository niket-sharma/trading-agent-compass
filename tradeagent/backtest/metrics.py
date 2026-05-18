"""Backtest performance metrics.

All functions are pure: (equity_series | returns_series) -> scalar.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def cagr(equity: pd.Series) -> float:
    """Compound Annual Growth Rate from an equity curve (dollar values)."""
    if len(equity) < 2:
        return 0.0
    years = len(equity) / 252.0
    if years == 0 or equity.iloc[0] <= 0:
        return 0.0
    return float((equity.iloc[-1] / equity.iloc[0]) ** (1.0 / years) - 1.0)


def max_drawdown(equity: pd.Series) -> float:
    """Maximum peak-to-trough drawdown as a negative fraction (e.g. -0.35)."""
    if equity.empty:
        return 0.0
    running_max = equity.cummax()
    dd = (equity - running_max) / running_max.replace(0, float("nan"))
    return float(dd.min())


def sharpe(equity: pd.Series, risk_free_annual: float = 0.0) -> float:
    """Annualized Sharpe ratio (daily returns, risk-free daily rate assumed 0 unless given)."""
    ret = equity.pct_change().dropna()
    if ret.empty or ret.std() == 0:
        return 0.0
    rf_daily = (1 + risk_free_annual) ** (1 / 252) - 1
    excess = ret - rf_daily
    return float(excess.mean() / excess.std() * np.sqrt(252))


def sortino(equity: pd.Series, risk_free_annual: float = 0.0) -> float:
    """Annualized Sortino ratio (penalizes downside deviation only)."""
    ret = equity.pct_change().dropna()
    if ret.empty:
        return 0.0
    rf_daily = (1 + risk_free_annual) ** (1 / 252) - 1
    excess = ret - rf_daily
    downside = excess[excess < 0]
    if downside.empty or downside.std() == 0:
        return 0.0
    return float(excess.mean() / downside.std() * np.sqrt(252))


def calmar(equity: pd.Series) -> float:
    """Calmar ratio = CAGR / |max drawdown|. Returns 0 if drawdown is 0."""
    mdd = abs(max_drawdown(equity))
    if mdd == 0:
        return 0.0
    return float(cagr(equity) / mdd)


def win_rate(pnl_series: pd.Series) -> float:
    """Fraction of trades with positive P&L."""
    if pnl_series.empty:
        return 0.0
    return float((pnl_series > 0).sum() / len(pnl_series))


def compute_all(equity: pd.Series) -> dict[str, float]:
    """Compute all standard metrics for an equity curve.

    Args:
        equity: Series of portfolio values, indexed by date, sorted ascending.

    Returns:
        Dict with keys: cagr, max_drawdown, sharpe, sortino, calmar.
        All values are floats (drawdown is negative).
    """
    return {
        "cagr": round(cagr(equity), 4),
        "max_drawdown": round(max_drawdown(equity), 4),
        "sharpe": round(sharpe(equity), 4),
        "sortino": round(sortino(equity), 4),
        "calmar": round(calmar(equity), 4),
    }
