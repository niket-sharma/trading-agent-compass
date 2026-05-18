"""Tests for tradeagent.strategy: allocation, signals, safety, tax."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

import pytest

from tradeagent.analysis.regime import Regime
from tradeagent.strategy.signals import Signal, generate_signals
from tradeagent.strategy.safety import apply_safety_overlays
from tradeagent.strategy.tax import (
    LotInfo,
    format_lot_summary,
    select_lots_to_sell,
    wash_sale_days_remaining,
)


# ── Minimal profile stub ──────────────────────────────────────────────────────


@dataclass
class _AllocWeights:
    base: float = 0.50
    leveraged_2x: float = 0.10
    leveraged_3x_long: float = 0.10
    leveraged_3x_medium: float = 0.10
    leveraged_3x_short: float = 0.05
    cash: float = 0.15


@dataclass
class _Profile:
    name: str = "moderate"
    description: str = ""
    risk_level: int = 5
    aggression: int = 5
    max_leverage: float = 2.0
    volatility_tolerance: str = "medium"
    trading_intensity: str = "moderate"
    st_tax_rate: float = 0.32
    lt_tax_rate: float = 0.15
    recurring_contribution: Any = field(default_factory=lambda: type("RC", (), {"amount": 1000, "frequency": "monthly"})())
    constraints: list = field(default_factory=list)
    allocation_by_regime: dict[str, Any] = field(default_factory=lambda: {
        "strong_bull": _AllocWeights(base=0.40, leveraged_2x=0.10, leveraged_3x_long=0.15, leveraged_3x_medium=0.20, leveraged_3x_short=0.10, cash=0.05),
        "bull": _AllocWeights(base=0.50, leveraged_2x=0.10, leveraged_3x_long=0.10, leveraged_3x_medium=0.10, leveraged_3x_short=0.05, cash=0.15),
        "neutral": _AllocWeights(base=0.55, leveraged_2x=0.05, leveraged_3x_long=0.05, leveraged_3x_medium=0.05, leveraged_3x_short=0.00, cash=0.30),
        "bear": _AllocWeights(base=0.40, leveraged_2x=0.00, leveraged_3x_long=0.05, leveraged_3x_medium=0.00, leveraged_3x_short=0.05, cash=0.50),
        "strong_bear": _AllocWeights(base=0.20, leveraged_2x=0.00, leveraged_3x_long=0.00, leveraged_3x_medium=0.00, leveraged_3x_short=0.10, cash=0.70),
    })


_PROFILE = _Profile()


# ── Allocation tests ──────────────────────────────────────────────────────────


class TestAllocation:
    def test_weights_sum_to_one(self):
        from tradeagent.strategy.allocation import compute_target_weights
        for regime in Regime:
            w = compute_target_weights(regime, _PROFILE, ema_alpha=1.0)
            assert sum(w.values()) == pytest.approx(1.0, abs=1e-6), f"Failed for {regime}"

    def test_strong_bull_has_more_leverage_than_neutral(self):
        from tradeagent.strategy.allocation import compute_target_weights
        sb = compute_target_weights(Regime.STRONG_BULL, _PROFILE, ema_alpha=1.0)
        n = compute_target_weights(Regime.NEUTRAL, _PROFILE, ema_alpha=1.0)
        sb_lev = sb["leveraged_3x_long"] + sb["leveraged_3x_medium"] + sb["leveraged_3x_short"]
        n_lev = n["leveraged_3x_long"] + n["leveraged_3x_medium"] + n["leveraged_3x_short"]
        assert sb_lev >= n_lev

    def test_strong_bear_has_more_cash_than_bull(self):
        from tradeagent.strategy.allocation import compute_target_weights
        sb = compute_target_weights(Regime.STRONG_BEAR, _PROFILE, ema_alpha=1.0)
        bu = compute_target_weights(Regime.BULL, _PROFILE, ema_alpha=1.0)
        assert sb["cash"] > bu["cash"]

    def test_drawdown_throttle_reduces_leverage(self):
        from tradeagent.strategy.allocation import compute_target_weights
        normal = compute_target_weights(Regime.BULL, _PROFILE, ema_alpha=1.0, current_drawdown=-0.05)
        throttled = compute_target_weights(Regime.BULL, _PROFILE, ema_alpha=1.0, current_drawdown=-0.30)
        normal_lev = normal["leveraged_3x_long"] + normal["leveraged_3x_medium"]
        throttled_lev = throttled["leveraged_3x_long"] + throttled["leveraged_3x_medium"]
        assert throttled_lev <= normal_lev

    def test_ema_smoothing_blends_weights(self):
        from tradeagent.strategy.allocation import compute_target_weights
        prev = {"base": 1.0, "leveraged_2x": 0.0, "leveraged_3x_long": 0.0, "leveraged_3x_medium": 0.0, "leveraged_3x_short": 0.0, "cash": 0.0}
        smoothed = compute_target_weights(Regime.BULL, _PROFILE, ema_alpha=0.5, prev_weights=prev)
        # base should be between 0.5 (full EMA) and raw target
        assert 0.0 < smoothed["base"] < 1.0

    def test_string_regime_works(self):
        from tradeagent.strategy.allocation import compute_target_weights
        w = compute_target_weights("bull", _PROFILE, ema_alpha=1.0)
        assert sum(w.values()) == pytest.approx(1.0, abs=1e-6)


# ── Signal generation tests ───────────────────────────────────────────────────


class TestSignals:
    def _make_signals(self, regime="bull", target_pct=0.10, current_pct=0.0):
        target_weights = {
            "base": target_pct,
            "leveraged_2x": 0.0,
            "leveraged_3x_long": 0.0,
            "leveraged_3x_medium": 0.0,
            "leveraged_3x_short": 0.0,
            "cash": 1.0 - target_pct,
        }
        current_weights = {k: 0.0 for k in target_weights}
        current_weights["base"] = current_pct
        current_weights["cash"] = 1.0 - current_pct
        return generate_signals(regime, target_weights, current_weights, {}, {"QQQ": 450.0})

    def test_buy_signal_when_underweight(self):
        sigs = self._make_signals(target_pct=0.50, current_pct=0.0)
        buy_sigs = [s for s in sigs if s.action == "BUY"]
        assert len(buy_sigs) > 0

    def test_sell_signal_when_overweight(self):
        sigs = generate_signals(
            "bear",
            {"base": 0.10, "leveraged_2x": 0.0, "leveraged_3x_long": 0.0, "leveraged_3x_medium": 0.0, "leveraged_3x_short": 0.0, "cash": 0.90},
            {"base": 0.60, "leveraged_2x": 0.0, "leveraged_3x_long": 0.0, "leveraged_3x_medium": 0.0, "leveraged_3x_short": 0.0, "cash": 0.40},
            {},
            {},
        )
        sell_sigs = [s for s in sigs if s.action == "SELL"]
        assert len(sell_sigs) > 0

    def test_no_signal_within_threshold(self):
        sigs = self._make_signals(target_pct=0.502, current_pct=0.500)
        assert len(sigs) == 0

    def test_sells_before_buys(self):
        sigs = generate_signals(
            "bull",
            {"base": 0.60, "leveraged_2x": 0.10, "leveraged_3x_long": 0.0, "leveraged_3x_medium": 0.0, "leveraged_3x_short": 0.0, "cash": 0.30},
            {"base": 0.20, "leveraged_2x": 0.60, "leveraged_3x_long": 0.0, "leveraged_3x_medium": 0.0, "leveraged_3x_short": 0.0, "cash": 0.20},
            {},
            {},
        )
        sell_idx = [i for i, s in enumerate(sigs) if s.action == "SELL"]
        buy_idx = [i for i, s in enumerate(sigs) if s.action == "BUY"]
        if sell_idx and buy_idx:
            assert max(sell_idx) < min(buy_idx)

    def test_bear_short_uses_sqqq(self):
        sigs = generate_signals(
            "strong_bear",
            {"base": 0.2, "leveraged_2x": 0.0, "leveraged_3x_long": 0.0, "leveraged_3x_medium": 0.0, "leveraged_3x_short": 0.15, "cash": 0.65},
            {k: 0.0 for k in ["base", "leveraged_2x", "leveraged_3x_long", "leveraged_3x_medium", "leveraged_3x_short", "cash"]},
            {},
            {},
        )
        short_sigs = [s for s in sigs if s.bucket == "leveraged_3x_short"]
        if short_sigs:
            assert short_sigs[0].ticker == "SQQQ"

    def test_confidence_in_bounds(self):
        sigs = self._make_signals(target_pct=0.50, current_pct=0.0)
        for s in sigs:
            assert 0.0 <= s.confidence <= 1.0


# ── Safety overlay tests ──────────────────────────────────────────────────────


def _sig(bucket: str = "base", target_pct: float = 0.10) -> Signal:
    return Signal(
        action="BUY",
        ticker="QQQ",
        bucket=bucket,
        target_pct=target_pct,
        limit_price=None,
        urgency="medium",
        confidence=0.7,
    )


class TestSafety:
    def test_no_throttle_normal_conditions(self):
        sig = _sig("base", 0.10)
        # regime_score=0.0 is equidistant from all boundaries (±0.20 and ±0.60), safely inside neutral
        result = apply_safety_overlays([sig], vix_level=15.0, consecutive_losses=0, regime_score=0.0)
        assert result[0].target_pct == pytest.approx(0.10)

    def test_high_vix_reduces_leveraged(self):
        sig = _sig("leveraged_3x_long", 0.15)
        result = apply_safety_overlays([sig], vix_level=40.0, consecutive_losses=0, regime_score=0.0)
        assert result[0].target_pct < 0.15

    def test_high_vix_does_not_affect_base(self):
        sig = _sig("base", 0.50)
        result = apply_safety_overlays([sig], vix_level=40.0, consecutive_losses=0, regime_score=0.0)
        assert result[0].target_pct == pytest.approx(0.50)

    def test_consecutive_loss_halves_size(self):
        sig = _sig("base", 0.20)
        result = apply_safety_overlays([sig], consecutive_losses=5, consecutive_loss_throttle=3, regime_score=0.0)
        assert result[0].target_pct < 0.20

    def test_near_boundary_reduces_size(self):
        sig = _sig("base", 0.20)
        # score=0.21 is very close to the bull boundary of 0.20
        result = apply_safety_overlays([sig], regime_score=0.21, confidence_throttle_zone=0.10)
        assert result[0].target_pct < 0.20

    def test_safety_multiplier_in_reasoning(self):
        sig = _sig("leveraged_3x_long", 0.10)
        result = apply_safety_overlays([sig], vix_level=35.0)
        assert "safety_multiplier" in result[0].reasoning

    def test_returns_new_list(self):
        sigs = [_sig("base", 0.10)]
        result = apply_safety_overlays(sigs, vix_level=15.0)
        assert result is not sigs


# ── Tax tests ─────────────────────────────────────────────────────────────────


class TestTax:
    def _lot(self, shares=100.0, cost=100.0, pdate=None, price=120.0, lot_id="a") -> LotInfo:
        return LotInfo(
            lot_id=lot_id,
            ticker="QQQ",
            shares=shares,
            cost_basis=cost,
            purchase_date=pdate or date(2022, 1, 1),
            current_price=price,
        )

    def test_hifo_selects_highest_cost_first(self):
        lots = [self._lot(100, 80, lot_id="low"), self._lot(100, 150, lot_id="high")]
        selected, _ = select_lots_to_sell(lots, 50)
        assert selected[0].lot_id == "high"

    def test_tax_loss_harvesting_prefers_losses(self):
        loss_lot = self._lot(100, 200, price=120, lot_id="loss")  # underwater
        gain_lot = self._lot(100, 80, price=120, lot_id="gain")   # in profit
        selected, wash = select_lots_to_sell([gain_lot, loss_lot], 50, prefer_losses=True)
        assert selected[0].lot_id == "loss"
        assert wash is True

    def test_partial_sell(self):
        lots = [self._lot(200, 100)]
        selected, _ = select_lots_to_sell(lots, 50)
        assert len(selected) == 1
        assert selected[0].shares == 200  # full lot selected, partial will happen in engine

    def test_empty_lots(self):
        selected, wash = select_lots_to_sell([], 50)
        assert selected == []
        assert wash is False

    def test_wash_sale_days_remaining(self):
        sold_date = date(2024, 1, 1)
        today = date(2024, 1, 20)
        remaining = wash_sale_days_remaining(sold_date, today)
        assert remaining == 12  # 31 - 19 days elapsed

    def test_wash_sale_expired(self):
        sold_date = date(2024, 1, 1)
        today = date(2024, 2, 15)
        remaining = wash_sale_days_remaining(sold_date, today)
        assert remaining == 0

    def test_is_long_term(self):
        lot = LotInfo("a", "QQQ", 100, 100.0, date(2020, 1, 1), 200.0)
        assert lot.is_long_term is True

    def test_is_short_term(self):
        lot = LotInfo("a", "QQQ", 100, 100.0, date.today(), 120.0)
        assert lot.is_long_term is False

    def test_format_lot_summary(self):
        lot = self._lot()
        s = format_lot_summary(lot)
        assert "QQQ" in s
        assert "$100.00" in s
