"""Rules-based 5-state regime classifier.

Regime states ordered bearish → bullish:
    STRONG_BEAR → BEAR → NEUTRAL → BULL → STRONG_BULL

All functions are pure: caller loads data, passes DataFrames in.
No I/O, no Streamlit calls, no side effects.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any

import numpy as np
import pandas as pd

from tradeagent.analysis.technical import compute_sma, compute_trend_slope


class Regime(StrEnum):
    STRONG_BULL = "strong_bull"
    BULL = "bull"
    NEUTRAL = "neutral"
    BEAR = "bear"
    STRONG_BEAR = "strong_bear"


@dataclass
class RegimeReading:
    date: date
    regime: Regime
    score: float  # composite in [-1, 1]
    components: dict[str, float] = field(default_factory=dict)
    regime_age_days: int = 1
    sentiment_included: bool = False


# ── Component scoring helpers ────────────────────────────────────────────────


def _score_trend_slope(slope: float, t: dict[str, float]) -> float:
    """Map annualized 200d slope to [-1, 1]."""
    if np.isnan(slope):
        return 0.0
    sb, b, br, sbr = t["strong_bull_threshold"], t["bull_threshold"], t["bear_threshold"], t["strong_bear_threshold"]
    if slope >= sb:
        return 1.0
    if slope >= b:
        return 0.5 + 0.5 * (slope - b) / (sb - b)
    if slope >= 0:
        return 0.5 * slope / b
    if slope >= br:
        return -0.5 * abs(slope) / abs(br)
    if slope >= sbr:
        return -0.5 - 0.5 * (abs(slope) - abs(br)) / (abs(sbr) - abs(br))
    return -1.0


def _score_vix(level: float, change_20d: float, t: dict[str, Any]) -> tuple[float, float]:
    """Returns (level_score, change_score), each in [-1, 1]."""
    lo, elev, hi, ext = t["low"], t["elevated"], t["high"], t["extreme"]
    if level <= lo:
        level_score = 1.0
    elif level <= elev:
        level_score = 1.0 - (level - lo) / (elev - lo)
    elif level <= hi:
        level_score = -(level - elev) / (hi - elev) * 0.5
    elif level <= ext:
        level_score = -0.5 - 0.5 * (level - hi) / (ext - hi)
    else:
        level_score = -1.0

    # Rising VIX → bearish; ±10-point change → ±1
    change_score = max(-1.0, min(1.0, -change_20d / 10.0))
    return level_score, change_score


def _score_drawdown(dd: float, t: dict[str, float]) -> float:
    """dd is a negative fraction (e.g. -0.15). Returns 0 (no penalty) to -1."""
    mild, moderate, deep = t["mild"], t["moderate"], t["deep"]
    if dd >= mild:
        return 0.0
    if dd >= moderate:
        return -0.5 * (dd - mild) / (moderate - mild)
    if dd >= deep:
        return -0.5 - 0.5 * (dd - moderate) / (deep - moderate)
    return -1.0


def _score_breadth(pct: float, t: dict[str, float]) -> float:
    """pct in [0, 1] = fraction of tickers above 50d MA. Returns [-1, 1]."""
    sb, b, br, sbr = t["strong_bull"], t["bull"], t["bear"], t["strong_bear"]
    if pct >= sb:
        return 1.0
    if pct >= b:
        return 0.5 + 0.5 * (pct - b) / (sb - b)
    if pct >= br:
        return -0.5 + (pct - br) / (b - br)
    if pct >= sbr:
        return -0.5 - 0.5 * (br - pct) / (br - sbr)
    return -1.0


def _score_yield_curve(spread: float, t: dict[str, float]) -> float:
    """spread = 10y - 2y in percentage points. Returns [-1, 1]."""
    pos, neg = t["positive_threshold"], t["negative_threshold"]
    if spread >= pos:
        return 0.5
    if spread >= 0:
        return 0.5 * spread / pos
    if spread >= neg:
        return -0.5 * abs(spread) / abs(neg)
    return -1.0


def _composite_to_regime(score: float, bp: dict[str, float]) -> Regime:
    if score >= bp["strong_bull"]:
        return Regime.STRONG_BULL
    if score >= bp["bull"]:
        return Regime.BULL
    if score >= bp["neutral"]:
        return Regime.NEUTRAL
    if score >= bp["bear"]:
        return Regime.BEAR
    return Regime.STRONG_BEAR


def _compute_breadth(breadth_prices: dict[str, pd.DataFrame], as_of: date | None) -> float:
    """Fraction of single-name tickers above their 50d MA as of `as_of`."""
    if not breadth_prices:
        return 0.5
    above = total = 0
    for df in breadth_prices.values():
        if df.empty:
            continue
        close = df["close"] if "close" in df.columns else df.iloc[:, -1]
        if as_of is not None and "date" in df.columns:
            close = close[pd.to_datetime(df["date"]).dt.date <= as_of]
        close = close.reset_index(drop=True)
        if len(close) < 50:
            continue
        sma50 = float(compute_sma(close, 50).iloc[-1])
        current = float(close.iloc[-1])
        total += 1
        if not np.isnan(sma50) and current > sma50:
            above += 1
    return above / total if total > 0 else 0.5


def _compute_yield_curve_score(
    macro: dict[str, pd.DataFrame], as_of: date | None, t: dict[str, float]
) -> float:
    dgs10 = macro.get("DGS10", pd.DataFrame())
    dgs2 = macro.get("DGS2", pd.DataFrame())
    if dgs10.empty or dgs2.empty:
        return 0.0

    def _last(df: pd.DataFrame) -> float:
        if as_of is not None and "date" in df.columns:
            df = df[pd.to_datetime(df["date"]).dt.date <= as_of]
        if df.empty:
            return float("nan")
        col = "value" if "value" in df.columns else df.columns[-1]
        return float(df[col].dropna().iloc[-1])

    r10, r2 = _last(dgs10), _last(dgs2)
    if np.isnan(r10) or np.isnan(r2):
        return 0.0
    return _score_yield_curve(r10 - r2, t)


def _regime_age(history: list[Regime], current: Regime) -> int:
    """Count consecutive trailing entries matching `current`, including today."""
    count = 0
    for r in reversed(history):
        if r == current:
            count += 1
        else:
            break
    return count + 1  # +1 for today


# ── Public API ───────────────────────────────────────────────────────────────


def classify_regime(
    ndx: pd.DataFrame,
    vix: pd.DataFrame,
    macro: dict[str, pd.DataFrame],
    breadth_prices: dict[str, pd.DataFrame],
    *,
    params: dict[str, Any] | None = None,
    as_of: date | None = None,
    sentiment_score: float | None = None,
    regime_history: list[Regime] | None = None,
) -> RegimeReading:
    """Classify the current market regime using a weighted composite of indicators.

    Args:
        ndx: Daily OHLCV for the NDX proxy (QQQ or ^NDX), sorted ascending.
             Required columns: ['close'] plus optionally ['date'].
        vix: Daily VIX data. Required columns: ['close'] plus optionally ['date'].
        macro: Dict keyed by FRED series ID (e.g. 'DGS10', 'DGS2').
               Each value is a DataFrame with columns ['date', 'value'].
        breadth_prices: Dict {ticker: price_df} for single-name universe tickers.
                        price_df must have column 'close' and optionally 'date'.
        params: Regime config dict from strategy_params.yaml['regime'].
                Defaults to get_config().strategy.regime if None.
        as_of: Compute regime as of this date (inclusive). None = last available.
               All DataFrames are filtered to <= as_of (no lookahead).
        sentiment_score: Aggregate sentiment in [-1, 1], or None if no key.
        regime_history: Previous Regime values, oldest first.
                        Used to compute regime_age_days.

    Returns:
        RegimeReading with date, regime, score, components, regime_age_days,
        sentiment_included.
    """
    if params is None:
        from tradeagent.config import get_config
        params = get_config().strategy.regime

    def _filter_df(df: pd.DataFrame) -> pd.DataFrame:
        if as_of is None or df.empty:
            return df
        if "date" in df.columns:
            mask = pd.to_datetime(df["date"]).dt.date <= as_of
            return df[mask].copy()
        return df

    ndx_f = _filter_df(ndx)
    vix_f = _filter_df(vix)

    ndx_close = (
        ndx_f["close"].reset_index(drop=True)
        if "close" in ndx_f.columns
        else ndx_f.iloc[:, -1].reset_index(drop=True)
    )
    vix_close = (
        vix_f["close"].reset_index(drop=True)
        if "close" in vix_f.columns
        else vix_f.iloc[:, -1].reset_index(drop=True)
    )

    # Determine eval date
    if as_of is not None:
        eval_date = as_of
    elif "date" in ndx_f.columns and not ndx_f.empty:
        eval_date = pd.to_datetime(ndx_f["date"].iloc[-1]).date()
    elif not ndx_f.empty:
        eval_date = pd.Timestamp.today().date()
    else:
        eval_date = pd.Timestamp.today().date()

    # ── 1. NDX 200d slope ──────────────────────────────────────────────────
    slope_series = compute_trend_slope(ndx_close, window=min(200, len(ndx_close)))
    slope = float(slope_series.iloc[-1]) if not slope_series.empty else float("nan")
    trend_score = _score_trend_slope(slope, params["trend_slope"])

    # ── 2. 50/200 MA cross ─────────────────────────────────────────────────
    sma50 = float(compute_sma(ndx_close, min(50, len(ndx_close))).iloc[-1])
    sma200 = float(compute_sma(ndx_close, min(200, len(ndx_close))).iloc[-1])
    ma_cross_score = 0.0 if np.isnan(sma50) or np.isnan(sma200) else 1.0 if sma50 > sma200 else -1.0

    # ── 3. VIX level + 20d change ─────────────────────────────────────────
    if vix_close.empty:
        vix_level, vix_change_20d = 20.0, 0.0
    else:
        vix_level = float(vix_close.iloc[-1])
        vix_20d_ago = float(vix_close.iloc[-21]) if len(vix_close) > 20 else vix_level
        vix_change_20d = vix_level - vix_20d_ago
    vix_level_score, vix_change_score = _score_vix(vix_level, vix_change_20d, params["vix"])

    # ── 4. NDX drawdown from 52w high ─────────────────────────────────────
    if ndx_close.empty:
        dd_score = 0.0
        drawdown = 0.0
    else:
        high_52w = float(ndx_close.rolling(min(252, len(ndx_close)), min_periods=1).max().iloc[-1])
        current = float(ndx_close.iloc[-1])
        drawdown = (current / high_52w - 1.0) if high_52w > 0 else 0.0
        dd_score = _score_drawdown(drawdown, params["drawdown"])

    # ── 5. Breadth ─────────────────────────────────────────────────────────
    pct_above = _compute_breadth(breadth_prices, as_of)
    breadth_score = _score_breadth(pct_above, params["breadth"])

    # ── 6. Yield curve ─────────────────────────────────────────────────────
    yc_score = _compute_yield_curve_score(macro, as_of, params["yield_curve"])

    # ── 7. Sentiment (optional) ────────────────────────────────────────────
    sentiment_included = sentiment_score is not None
    sent_score = float(sentiment_score) if sentiment_included else 0.0

    # ── Weighted composite ─────────────────────────────────────────────────
    # Fixed weights
    ma_w = float(params["ma_cross"]["weight"])         # 0.20
    vix_chg_w = float(params["vix"]["change_20d_weight"])  # 0.10
    brd_w = float(params["breadth"]["weight"])          # 0.15
    yc_w = float(params["yield_curve"]["weight"])       # 0.10
    sent_w = float(params["sentiment"]["weight"]) if sentiment_included else 0.0  # 0.15

    fixed_w = ma_w + vix_chg_w + brd_w + yc_w + sent_w
    remaining = 1.0 - fixed_w  # weight for trend, VIX level, drawdown
    trend_w = remaining * 0.50
    vix_lvl_w = remaining * 0.30
    dd_w = remaining * 0.20

    composite = (
        trend_w * trend_score
        + ma_w * ma_cross_score
        + vix_lvl_w * vix_level_score
        + vix_chg_w * vix_change_score
        + dd_w * dd_score
        + brd_w * breadth_score
        + yc_w * yc_score
        + sent_w * sent_score
    )
    composite = max(-1.0, min(1.0, composite))

    regime = _composite_to_regime(composite, params["composite_breakpoints"])
    age = _regime_age(regime_history or [], regime)

    components: dict[str, float] = {
        "trend_slope": round(trend_score, 4),
        "ma_cross": round(ma_cross_score, 4),
        "vix_level": round(vix_level_score, 4),
        "vix_change_20d": round(vix_change_score, 4),
        "drawdown": round(dd_score, 4),
        "breadth": round(breadth_score, 4),
        "yield_curve": round(yc_score, 4),
    }
    if sentiment_included:
        components["sentiment"] = round(sent_score, 4)

    return RegimeReading(
        date=eval_date,
        regime=regime,
        score=round(composite, 4),
        components=components,
        regime_age_days=age,
        sentiment_included=sentiment_included,
    )
