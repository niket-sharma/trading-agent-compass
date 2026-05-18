"""Tests for tradeagent.analysis.technical."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tradeagent.analysis.technical import (
    compute_atr,
    compute_bollinger_bands,
    compute_ema,
    compute_macd,
    compute_realized_vol,
    compute_return,
    compute_rolling_sharpe,
    compute_rsi,
    compute_sma,
    compute_technical_score,
    compute_trend_slope,
    compute_vol_of_vol,
    compute_vwap,
    golden_death_cross,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _price_df(n: int = 300, seed: int = 42, trend: float = 0.0005) -> pd.DataFrame:
    """Synthetic price DataFrame with n rows and a controllable daily trend."""
    rng = np.random.default_rng(seed)
    returns = rng.normal(trend, 0.012, n)
    prices = 100.0 * np.cumprod(1 + returns)
    dates = pd.bdate_range(end=pd.Timestamp("2024-12-31"), periods=n, tz="UTC")
    return pd.DataFrame(
        {
            "date": dates,
            "open": prices * 0.995,
            "high": prices * 1.010,
            "low": prices * 0.990,
            "close": prices,
            "adj_close": prices,
            "volume": np.full(n, 1_000_000, dtype=int),
        }
    )


# ── SMA / EMA ─────────────────────────────────────────────────────────────────


def test_sma_length():
    close = pd.Series(range(1, 11), dtype=float)
    result = compute_sma(close, 3)
    assert result.isna().sum() == 2  # first 2 are NaN
    assert result.iloc[-1] == pytest.approx(9.0)


def test_ema_length():
    close = pd.Series([1.0] * 20)
    result = compute_ema(close, span=10)
    assert len(result) == 20
    assert result.iloc[-1] == pytest.approx(1.0, abs=1e-6)


def test_sma_known_value():
    close = pd.Series([2.0, 4.0, 6.0, 8.0, 10.0])
    assert compute_sma(close, 3).iloc[-1] == pytest.approx(8.0)


# ── VWAP ──────────────────────────────────────────────────────────────────────


def test_vwap_returns_series():
    df = _price_df(50)
    vwap = compute_vwap(df, period=20)
    assert isinstance(vwap, pd.Series)
    assert len(vwap) == 50


# ── RSI ───────────────────────────────────────────────────────────────────────


def test_rsi_range():
    df = _price_df(100)
    rsi = compute_rsi(df["close"], period=14)
    valid = rsi.dropna()
    assert (valid >= 0).all() and (valid <= 100).all()


def test_rsi_nan_prefix():
    df = _price_df(20)
    rsi = compute_rsi(df["close"], period=14)
    # ewm with min_periods=14: first 13 are NaN
    assert rsi.iloc[0:13].isna().all()


def test_rsi_flat_price():
    close = pd.Series([100.0] * 30)
    rsi = compute_rsi(close, period=14)
    # all gains and losses are 0 → RSI is NaN (0/0)
    assert rsi.dropna().empty or (rsi.dropna() == 50.0).all()


# ── MACD ─────────────────────────────────────────────────────────────────────


def test_macd_columns():
    df = _price_df(60)
    macd = compute_macd(df["close"])
    assert set(macd.columns) == {"macd", "signal", "histogram"}


def test_macd_histogram_relation():
    df = _price_df(60)
    m = compute_macd(df["close"])
    # histogram must equal macd - signal
    pd.testing.assert_series_equal(m["histogram"], m["macd"] - m["signal"], check_names=False)


# ── Bollinger Bands ───────────────────────────────────────────────────────────


def test_bb_columns():
    df = _price_df(50)
    bb = compute_bollinger_bands(df["close"])
    assert set(bb.columns) == {"upper", "mid", "lower", "pct_b"}


def test_bb_ordering():
    df = _price_df(100)
    bb = compute_bollinger_bands(df["close"]).dropna()
    assert (bb["upper"] >= bb["mid"]).all()
    assert (bb["mid"] >= bb["lower"]).all()


# ── ATR ───────────────────────────────────────────────────────────────────────


def test_atr_positive():
    df = _price_df(50)
    atr = compute_atr(df).dropna()
    assert (atr > 0).all()


def test_atr_length():
    df = _price_df(30)
    atr = compute_atr(df, period=14)
    assert len(atr) == 30


# ── Trend slope ───────────────────────────────────────────────────────────────


def test_trend_slope_uptrend():
    """Strong uptrend → positive slope."""
    df = _price_df(250, trend=0.001)
    slope = compute_trend_slope(df["close"], window=200).dropna()
    assert float(slope.iloc[-1]) > 0


def test_trend_slope_downtrend():
    """Strong downtrend → negative slope."""
    df = _price_df(250, trend=-0.001)
    slope = compute_trend_slope(df["close"], window=200).dropna()
    assert float(slope.iloc[-1]) < 0


def test_trend_slope_nan_prefix():
    df = _price_df(210)
    slope = compute_trend_slope(df["close"], window=200)
    assert slope.iloc[:199].isna().all()
    assert not np.isnan(slope.iloc[-1])


# ── Golden / death cross ──────────────────────────────────────────────────────


def test_golden_cross_uptrend():
    df = _price_df(250, trend=0.001)
    cross = golden_death_cross(df["close"])
    assert int(cross.iloc[-1]) == 1


def test_death_cross_downtrend():
    df = _price_df(250, trend=-0.001)
    cross = golden_death_cross(df["close"])
    assert int(cross.iloc[-1]) == -1


def test_cross_values():
    df = _price_df(250)
    cross = golden_death_cross(df["close"])
    assert set(cross.unique()).issubset({-1, 0, 1})


# ── Momentum ─────────────────────────────────────────────────────────────────


def test_return_positive_trend():
    # Monotonically increasing prices guarantee a positive 30-day return
    close = pd.Series(range(50, 150, 1), dtype=float)
    r30 = compute_return(close, 30).dropna()
    assert float(r30.iloc[-1]) > 0


def test_rolling_sharpe_type():
    df = _price_df(300)
    sharpe = compute_rolling_sharpe(df["close"])
    assert isinstance(sharpe, pd.Series)


# ── Volatility ────────────────────────────────────────────────────────────────


def test_realized_vol_positive():
    df = _price_df(50)
    rv = compute_realized_vol(df["close"]).dropna()
    assert (rv > 0).all()


def test_vol_of_vol_type():
    df = _price_df(200)
    vov = compute_vol_of_vol(df["close"])
    assert isinstance(vov, pd.Series)


# ── Per-ticker score ──────────────────────────────────────────────────────────


def test_technical_score_keys():
    df = _price_df(250)
    score = compute_technical_score(df)
    assert set(score.keys()) == {"trend", "momentum", "rsi", "macd", "volatility", "composite"}


def test_technical_score_bounds():
    df = _price_df(250)
    score = compute_technical_score(df)
    for k, v in score.items():
        assert -1.0 <= v <= 1.0, f"{k}={v} out of bounds"


def test_technical_score_uptrend_positive():
    df = _price_df(300, trend=0.002)
    score = compute_technical_score(df)
    assert score["composite"] > 0


def test_technical_score_downtrend_negative():
    df = _price_df(300, trend=-0.002)
    score = compute_technical_score(df)
    assert score["composite"] < 0


def test_technical_score_as_of_idx_no_lookahead():
    df = _price_df(250)
    # Score at row 200 must be identical regardless of what follows
    score_at_200 = compute_technical_score(df, as_of_idx=200)
    score_from_truncated = compute_technical_score(df.iloc[:201])
    assert score_at_200["composite"] == pytest.approx(score_from_truncated["composite"], abs=1e-6)


def test_technical_score_small_df():
    """Should not crash on fewer than 200 rows."""
    df = _price_df(50)
    score = compute_technical_score(df)
    assert -1.0 <= score["composite"] <= 1.0
