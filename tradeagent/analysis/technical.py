"""Technical analysis indicators and per-ticker composite score.

All functions are pure: (DataFrame | Series) -> Series/DataFrame. No I/O.

Expected price DataFrame schema (from store.load_prices):
    columns: ['date', 'open', 'high', 'low', 'close', 'adj_close', 'volume']
    dtypes:  float64 (volume: int64); 'date' is datetime64[ns, UTC]
    order:   sorted ascending by date
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# ── Core indicators ─────────────────────────────────────────────────────────


def compute_sma(close: pd.Series, period: int) -> pd.Series:
    """Simple moving average."""
    return close.rolling(period, min_periods=period).mean()


def compute_ema(close: pd.Series, span: int) -> pd.Series:
    """Exponential moving average."""
    return close.ewm(span=span, adjust=False).mean()


def compute_vwap(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Volume-weighted average price over a rolling window.

    Args:
        df: DataFrame with columns [high, low, close, volume].
        period: rolling window in trading days.
    Returns:
        Series of VWAP values.
    """
    typical = (df["high"] + df["low"] + df["close"]) / 3
    vol = df["volume"].replace(0, float("nan"))
    return (typical * vol).rolling(period).sum() / vol.rolling(period).sum()


def compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder RSI.

    Args:
        close: Closing price series, sorted ascending.
        period: lookback window.
    Returns:
        RSI in [0, 100]; first `period` values are NaN.
    """
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    return 100.0 - 100.0 / (1.0 + rs)


def compute_macd(
    close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> pd.DataFrame:
    """MACD line, signal line, and histogram.

    Returns:
        DataFrame with columns ['macd', 'signal', 'histogram'].
    """
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return pd.DataFrame(
        {
            "macd": macd_line,
            "signal": signal_line,
            "histogram": macd_line - signal_line,
        }
    )


def compute_bollinger_bands(
    close: pd.Series, period: int = 20, num_std: float = 2.0
) -> pd.DataFrame:
    """Bollinger Bands with %B position indicator.

    Returns:
        DataFrame with columns ['upper', 'mid', 'lower', 'pct_b'].
        pct_b in [0, 1] when price is within bands (can exceed bounds on breakouts).
    """
    mid = close.rolling(period, min_periods=period).mean()
    std = close.rolling(period, min_periods=period).std()
    upper = mid + num_std * std
    lower = mid - num_std * std
    band_width = (upper - lower).replace(0, float("nan"))
    pct_b = (close - lower) / band_width
    return pd.DataFrame({"upper": upper, "mid": mid, "lower": lower, "pct_b": pct_b})


def compute_atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range (Wilder smoothing).

    Args:
        df: DataFrame with columns [high, low, close].
    Returns:
        ATR series; first `period` values are NaN.
    """
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(com=period - 1, min_periods=period).mean()


# ── Trend ────────────────────────────────────────────────────────────────────


def compute_trend_slope(close: pd.Series, window: int = 200) -> pd.Series:
    """Annualized slope of log-price OLS regression over a rolling window.

    Returns fractional annual rate (e.g. 0.15 means +15 %/yr).
    Positive → uptrend, negative → downtrend.
    """
    log_close = np.log(close)
    x = np.arange(window, dtype=float)
    x -= x.mean()
    x_var = float(np.dot(x, x))

    def _slope(y: np.ndarray) -> float:
        if np.isnan(y).any():
            return float("nan")
        return float(np.dot(x, y - y.mean()) / x_var) * 252  # annualize

    return log_close.rolling(window, min_periods=window).apply(_slope, raw=True)


def golden_death_cross(close: pd.Series, fast: int = 50, slow: int = 200) -> pd.Series:
    """Golden cross (+1) vs death cross (-1) vs undefined (0)."""
    sma_fast = compute_sma(close, fast)
    sma_slow = compute_sma(close, slow)
    diff = sma_fast - sma_slow
    return diff.apply(lambda v: 1 if v > 0 else (-1 if v < 0 else 0)).where(
        sma_fast.notna() & sma_slow.notna(), 0
    )


# ── Momentum ──────────────────────────────────────────────────────────────────


def compute_return(close: pd.Series, days: int) -> pd.Series:
    """Trailing N-day total return."""
    return close / close.shift(days) - 1.0


def compute_rolling_sharpe(close: pd.Series, window: int = 252) -> pd.Series:
    """Annualized Sharpe (risk-free = 0) over a rolling window."""
    daily = close.pct_change()
    mu = daily.rolling(window, min_periods=window).mean()
    sigma = daily.rolling(window, min_periods=window).std()
    return (mu / sigma.replace(0, float("nan"))) * np.sqrt(252)


# ── Volatility ────────────────────────────────────────────────────────────────


def compute_realized_vol(close: pd.Series, window: int = 20) -> pd.Series:
    """Annualized realized volatility (std of daily log returns x sqrt(252))."""
    log_ret = np.log(close / close.shift(1))
    return log_ret.rolling(window, min_periods=window).std() * np.sqrt(252)


def compute_vol_of_vol(
    close: pd.Series, vol_window: int = 20, vov_window: int = 60
) -> pd.Series:
    """Volatility of realized volatility — measure of regime instability."""
    rv = compute_realized_vol(close, vol_window)
    return rv.rolling(vov_window, min_periods=vov_window).std()


# ── Per-ticker composite score ────────────────────────────────────────────────


def _clip(x: float) -> float:
    return max(-1.0, min(1.0, float(x)))


def compute_technical_score(
    df: pd.DataFrame,
    *,
    as_of_idx: int | None = None,
) -> dict[str, float]:
    """Compute per-ticker technical score in [-1, 1] with component breakdown.

    Args:
        df: Price DataFrame with columns [open, high, low, close, adj_close, volume],
            sorted ascending by date. Needs 200+ rows for full output.
        as_of_idx: Row index (0-based) to score as of. None = last row.
                   All rows after this index are ignored (no lookahead).
    Returns:
        Dict with keys: trend, momentum, rsi, macd, volatility, composite.
        All values in [-1, 1].
    """
    if as_of_idx is not None:
        df = df.iloc[: as_of_idx + 1].copy()

    close = df["close"].reset_index(drop=True)
    n = len(close)

    # ── Trend ──────────────────────────────────────────────────────────────
    w = min(200, n)
    slope_s = compute_trend_slope(close, window=w)
    slope = float(slope_s.iloc[-1]) if not slope_s.empty else float("nan")
    cross = int(golden_death_cross(close, fast=min(50, n), slow=min(200, n)).iloc[-1])

    if np.isnan(slope):
        trend_score = _clip(cross * 0.5)
    else:
        slope_norm = _clip(slope / 0.30)  # ±30 % annual → ±1
        trend_score = _clip(0.70 * slope_norm + 0.30 * cross)

    # ── Momentum ────────────────────────────────────────────────────────────
    r30 = float(compute_return(close, min(30, n - 1)).iloc[-1])
    r90 = float(compute_return(close, min(90, n - 1)).iloc[-1])
    r252 = float(compute_return(close, min(252, n - 1)).iloc[-1])
    m30 = 0.0 if np.isnan(r30) else _clip(r30 / 0.10)
    m90 = 0.0 if np.isnan(r90) else _clip(r90 / 0.20)
    m252 = 0.0 if np.isnan(r252) else _clip(r252 / 0.30)
    momentum_score = _clip(0.40 * m30 + 0.35 * m90 + 0.25 * m252)

    # ── RSI ────────────────────────────────────────────────────────────────
    rsi_val = float(compute_rsi(close, period=min(14, n - 1)).iloc[-1])
    rsi_score = 0.0 if np.isnan(rsi_val) else _clip(-(rsi_val - 50.0) / 50.0)

    # ── MACD ───────────────────────────────────────────────────────────────
    macd_df = compute_macd(close)
    hist = float(macd_df["histogram"].iloc[-1])
    if np.isnan(hist):
        macd_score = 0.0
    else:
        hist_std = float(macd_df["histogram"].rolling(90).std().iloc[-1])
        if np.isnan(hist_std) or hist_std == 0:
            macd_score = _clip(float(np.sign(hist)) * 0.5)
        else:
            macd_score = _clip(hist / (2.0 * hist_std))

    # ── Volatility ─────────────────────────────────────────────────────────
    rv = float(compute_realized_vol(close, window=min(20, n - 1)).iloc[-1])
    vol_score = 0.0 if np.isnan(rv) else _clip(0.5 - rv / 0.40)

    # ── Composite ──────────────────────────────────────────────────────────
    composite = _clip(
        0.35 * trend_score
        + 0.25 * momentum_score
        + 0.15 * rsi_score
        + 0.15 * macd_score
        + 0.10 * vol_score
    )

    return {
        "trend": round(trend_score, 4),
        "momentum": round(momentum_score, 4),
        "rsi": round(rsi_score, 4),
        "macd": round(macd_score, 4),
        "volatility": round(vol_score, 4),
        "composite": round(composite, 4),
    }
