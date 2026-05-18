"""Tests for tradeagent.analysis.regime."""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from tradeagent.analysis.regime import (
    Regime,
    RegimeReading,
    _compute_breadth,
    _regime_age,
    _score_breadth,
    _score_drawdown,
    _score_trend_slope,
    _score_vix,
    _score_yield_curve,
    classify_regime,
)

# ── Minimal params dict (mirrors strategy_params.yaml) ───────────────────────

_PARAMS: dict = {
    "trend_slope": {
        "strong_bull_threshold": 0.15,
        "bull_threshold": 0.05,
        "bear_threshold": -0.05,
        "strong_bear_threshold": -0.15,
    },
    "ma_cross": {"weight": 0.20},
    "vix": {
        "low": 15,
        "elevated": 20,
        "high": 25,
        "extreme": 35,
        "change_20d_weight": 0.10,
    },
    "drawdown": {"mild": -0.05, "moderate": -0.10, "deep": -0.20},
    "breadth": {
        "strong_bull": 0.80,
        "bull": 0.60,
        "bear": 0.40,
        "strong_bear": 0.20,
        "weight": 0.15,
    },
    "yield_curve": {
        "positive_threshold": 0.50,
        "negative_threshold": -0.25,
        "weight": 0.10,
    },
    "sentiment": {"weight": 0.15},
    "composite_breakpoints": {
        "strong_bull": 0.60,
        "bull": 0.20,
        "neutral": -0.20,
        "bear": -0.60,
    },
}


def _price_df(n: int, trend: float = 0.0005, seed: int = 42) -> pd.DataFrame:
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


def _vix_df(level: float = 18.0, n: int = 260) -> pd.DataFrame:
    dates = pd.bdate_range(end=pd.Timestamp("2024-12-31"), periods=n, tz="UTC")
    return pd.DataFrame({"date": dates, "close": np.full(n, level, dtype=float)})


def _macro() -> dict[str, pd.DataFrame]:
    dates = pd.bdate_range(end=pd.Timestamp("2024-12-31"), periods=100, tz="UTC")
    return {
        "DGS10": pd.DataFrame({"date": dates, "value": np.full(100, 4.5)}),
        "DGS2": pd.DataFrame({"date": dates, "value": np.full(100, 4.0)}),
    }


# ── Score helper unit tests ───────────────────────────────────────────────────


class TestScoreTrendSlope:
    def test_strong_bull(self):
        assert _score_trend_slope(0.20, _PARAMS["trend_slope"]) == pytest.approx(1.0)

    def test_strong_bear(self):
        assert _score_trend_slope(-0.20, _PARAMS["trend_slope"]) == pytest.approx(-1.0)

    def test_neutral(self):
        s = _score_trend_slope(0.0, _PARAMS["trend_slope"])
        assert s == pytest.approx(0.0)

    def test_nan(self):
        assert _score_trend_slope(float("nan"), _PARAMS["trend_slope"]) == 0.0


class TestScoreVix:
    def test_low_vix_bull(self):
        lvl, chg = _score_vix(12.0, 0.0, _PARAMS["vix"])
        assert lvl == pytest.approx(1.0)

    def test_extreme_vix_bear(self):
        lvl, _ = _score_vix(40.0, 0.0, _PARAMS["vix"])
        assert lvl == pytest.approx(-1.0)

    def test_rising_vix_negative_change(self):
        _, chg = _score_vix(20.0, 5.0, _PARAMS["vix"])
        assert chg < 0

    def test_falling_vix_positive_change(self):
        _, chg = _score_vix(20.0, -5.0, _PARAMS["vix"])
        assert chg > 0


class TestScoreDrawdown:
    def test_no_drawdown(self):
        assert _score_drawdown(-0.02, _PARAMS["drawdown"]) == 0.0

    def test_severe_drawdown(self):
        assert _score_drawdown(-0.30, _PARAMS["drawdown"]) == pytest.approx(-1.0)

    def test_mild_penalty(self):
        s = _score_drawdown(-0.10, _PARAMS["drawdown"])
        assert -0.6 < s < 0.0


class TestScoreBreadth:
    def test_all_above(self):
        assert _score_breadth(0.90, _PARAMS["breadth"]) == pytest.approx(1.0)

    def test_none_above(self):
        assert _score_breadth(0.10, _PARAMS["breadth"]) == pytest.approx(-1.0)

    def test_half(self):
        s = _score_breadth(0.50, _PARAMS["breadth"])
        assert -0.6 < s < 0.1


class TestScoreYieldCurve:
    def test_steep_positive(self):
        assert _score_yield_curve(1.0, _PARAMS["yield_curve"]) == pytest.approx(0.5)

    def test_inverted(self):
        assert _score_yield_curve(-0.5, _PARAMS["yield_curve"]) == pytest.approx(-1.0)

    def test_flat(self):
        s = _score_yield_curve(0.0, _PARAMS["yield_curve"])
        assert s == pytest.approx(0.0)


# ── Regime age ────────────────────────────────────────────────────────────────


def test_regime_age_all_same():
    history = [Regime.BULL] * 5
    assert _regime_age(history, Regime.BULL) == 6  # 5 + 1 for today


def test_regime_age_switch():
    history = [Regime.BEAR, Regime.NEUTRAL, Regime.BULL]
    assert _regime_age(history, Regime.BULL) == 2


def test_regime_age_empty():
    assert _regime_age([], Regime.NEUTRAL) == 1


# ── Breadth helper ────────────────────────────────────────────────────────────


def test_breadth_all_above():
    prices = {t: _price_df(60, trend=0.002) for t in ["A", "B", "C"]}
    pct = _compute_breadth(prices, as_of=None)
    assert 0.0 <= pct <= 1.0


def test_breadth_empty():
    assert _compute_breadth({}, None) == pytest.approx(0.5)


# ── Full classify_regime ──────────────────────────────────────────────────────


class TestClassifyRegime:
    def test_returns_reading(self):
        ndx = _price_df(260)
        vix = _vix_df(18.0)
        reading = classify_regime(ndx, vix, _macro(), {}, params=_PARAMS)
        assert isinstance(reading, RegimeReading)

    def test_regime_is_valid_enum(self):
        ndx = _price_df(260)
        vix = _vix_df(18.0)
        reading = classify_regime(ndx, vix, _macro(), {}, params=_PARAMS)
        assert reading.regime in list(Regime)

    def test_score_in_bounds(self):
        ndx = _price_df(260)
        vix = _vix_df(18.0)
        reading = classify_regime(ndx, vix, _macro(), {}, params=_PARAMS)
        assert -1.0 <= reading.score <= 1.0

    def test_bull_regime_with_uptrend(self):
        ndx = _price_df(300, trend=0.002)
        vix = _vix_df(12.0)  # low VIX
        reading = classify_regime(ndx, vix, _macro(), {}, params=_PARAMS)
        assert reading.regime in (Regime.BULL, Regime.STRONG_BULL)

    def test_bear_regime_with_downtrend(self):
        ndx = _price_df(300, trend=-0.002)
        vix = _vix_df(35.0)  # high VIX
        reading = classify_regime(ndx, vix, _macro(), {}, params=_PARAMS)
        assert reading.regime in (Regime.BEAR, Regime.STRONG_BEAR)

    def test_no_lookahead_with_as_of(self):
        ndx = _price_df(300)
        vix = _vix_df(18.0, n=300)
        as_of = date(2024, 11, 1)
        reading = classify_regime(ndx, vix, _macro(), {}, params=_PARAMS, as_of=as_of)
        assert reading.date == as_of

    def test_sentiment_included(self):
        ndx = _price_df(260)
        vix = _vix_df(18.0)
        reading = classify_regime(
            ndx, vix, _macro(), {}, params=_PARAMS, sentiment_score=0.5
        )
        assert reading.sentiment_included is True
        assert "sentiment" in reading.components

    def test_no_sentiment_excluded(self):
        ndx = _price_df(260)
        vix = _vix_df(18.0)
        reading = classify_regime(ndx, vix, _macro(), {}, params=_PARAMS, sentiment_score=None)
        assert reading.sentiment_included is False
        assert "sentiment" not in reading.components

    def test_component_keys(self):
        ndx = _price_df(260)
        vix = _vix_df(18.0)
        reading = classify_regime(ndx, vix, _macro(), {}, params=_PARAMS)
        expected = {"trend_slope", "ma_cross", "vix_level", "vix_change_20d", "drawdown", "breadth", "yield_curve"}
        assert expected.issubset(set(reading.components.keys()))

    def test_regime_age_first_call(self):
        ndx = _price_df(260)
        vix = _vix_df(18.0)
        reading = classify_regime(ndx, vix, _macro(), {}, params=_PARAMS)
        assert reading.regime_age_days >= 1

    def test_empty_vix_does_not_crash(self):
        ndx = _price_df(260)
        vix = pd.DataFrame({"close": []})
        reading = classify_regime(ndx, vix, _macro(), {}, params=_PARAMS)
        assert -1.0 <= reading.score <= 1.0

    def test_missing_macro_does_not_crash(self):
        ndx = _price_df(260)
        vix = _vix_df(18.0)
        reading = classify_regime(ndx, vix, {}, {}, params=_PARAMS)
        assert -1.0 <= reading.score <= 1.0
