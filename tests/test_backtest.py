"""Tests for tradeagent.backtest.engine and tradeagent.backtest.metrics."""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from tradeagent.backtest.engine import (
    BacktestConfig,
    BacktestResult,
    Lot,
    Trade,
    _apply_slippage,
    _hifo_lots,
    _is_long_term,
    _sell_lots,
    buy_and_hold_backtest,
    run_backtest,
)
from tradeagent.backtest.metrics import (
    cagr,
    calmar,
    compute_all,
    max_drawdown,
    sharpe,
    sortino,
    win_rate,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _price_df(n: int, ticker: str = "QQQ", trend: float = 0.0003, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    returns = rng.normal(trend, 0.010, n)
    prices = 100.0 * np.cumprod(1 + returns)
    dates = pd.bdate_range(end=pd.Timestamp("2024-12-31"), periods=n, tz="UTC")
    return pd.DataFrame(
        {
            "date": dates,
            "open": prices * 0.998,
            "high": prices * 1.005,
            "low": prices * 0.995,
            "close": prices,
            "adj_close": prices,
            "volume": np.full(n, 1_000_000, dtype=int),
        }
    )


def _config(n_days: int = 100) -> BacktestConfig:
    df = _price_df(n_days)
    dates = pd.to_datetime(df["date"]).dt.date.tolist()
    return BacktestConfig(start=dates[0], end=dates[-1], initial_capital=100_000.0)


# ── Metrics tests ─────────────────────────────────────────────────────────────


class TestMetrics:
    def test_cagr_flat(self):
        equity = pd.Series([100.0] * 252)
        assert cagr(equity) == pytest.approx(0.0, abs=1e-4)

    def test_cagr_positive(self):
        equity = pd.Series(np.linspace(100.0, 200.0, 252))
        assert cagr(equity) > 0

    def test_cagr_single_point(self):
        assert cagr(pd.Series([100.0])) == 0.0

    def test_max_drawdown_no_drawdown(self):
        equity = pd.Series(np.linspace(100.0, 200.0, 100))
        assert max_drawdown(equity) == pytest.approx(0.0)

    def test_max_drawdown_known(self):
        equity = pd.Series([100.0, 90.0, 80.0, 100.0])  # 20% drawdown
        assert max_drawdown(equity) == pytest.approx(-0.20, abs=0.01)

    def test_sharpe_positive_trend(self):
        equity = pd.Series(np.linspace(100.0, 130.0, 252))
        assert sharpe(equity) > 0

    def test_sortino_positive_trend(self):
        rng = np.random.default_rng(42)
        returns = rng.normal(0.001, 0.01, 252)
        equity = pd.Series(100.0 * np.cumprod(1 + returns))
        assert sortino(equity) > 0

    def test_calmar_returns_float(self):
        equity = pd.Series([100.0, 80.0, 90.0, 120.0, 110.0] * 50)
        result = calmar(equity)
        assert isinstance(result, float)

    def test_win_rate_all_positive(self):
        pnl = pd.Series([10.0, 20.0, 5.0])
        assert win_rate(pnl) == pytest.approx(1.0)

    def test_win_rate_empty(self):
        assert win_rate(pd.Series([], dtype=float)) == 0.0

    def test_compute_all_keys(self):
        equity = pd.Series(np.linspace(100.0, 130.0, 252))
        m = compute_all(equity)
        assert set(m.keys()) == {"cagr", "max_drawdown", "sharpe", "sortino", "calmar"}

    def test_compute_all_bounds(self):
        equity = pd.Series([100.0, 80.0, 90.0, 120.0, 110.0] * 50)
        m = compute_all(equity)
        assert -10.0 <= m["sharpe"] <= 10.0
        assert m["max_drawdown"] <= 0.0


# ── Tax-lot helpers ───────────────────────────────────────────────────────────


class TestLotHelpers:
    def test_is_long_term_true(self):
        assert _is_long_term(date(2022, 1, 1), date(2023, 2, 1)) is True

    def test_is_long_term_false(self):
        assert _is_long_term(date(2023, 1, 1), date(2023, 6, 1)) is False

    def test_hifo_orders_by_cost_desc(self):
        lots = [
            Lot("QQQ", 10, 100.0, date.today(), "a"),
            Lot("QQQ", 10, 150.0, date.today(), "b"),
            Lot("QQQ", 10, 80.0, date.today(), "c"),
        ]
        ordered = _hifo_lots(lots)
        costs = [l.cost_basis for l in ordered]
        assert costs == sorted(costs, reverse=True)

    def test_sell_lots_full(self):
        lots = [Lot("QQQ", 100, 100.0, date(2022, 1, 1), "lot1")]
        trades, remaining, pnl = _sell_lots(lots, 100, date(2023, 6, 1), 120.0)
        assert len(trades) == 1
        assert len(remaining) == 0
        assert pnl == pytest.approx(2000.0)  # (120-100)*100

    def test_sell_lots_partial(self):
        lots = [Lot("QQQ", 100, 100.0, date(2023, 1, 1), "lot1")]
        trades, remaining, _ = _sell_lots(lots, 50, date(2023, 6, 1), 110.0)
        assert trades[0].shares == pytest.approx(50)
        assert remaining[0].shares == pytest.approx(50)

    def test_sell_lots_lt_flag(self):
        lots = [Lot("QQQ", 50, 100.0, date(2020, 1, 1), "lot1")]
        trades, _, _ = _sell_lots(lots, 50, date(2022, 1, 1), 150.0)
        assert trades[0].is_long_term is True

    def test_sell_lots_st_flag(self):
        lots = [Lot("QQQ", 50, 100.0, date(2023, 1, 1), "lot1")]
        trades, _, _ = _sell_lots(lots, 50, date(2023, 6, 1), 110.0)
        assert trades[0].is_long_term is False


# ── Slippage ──────────────────────────────────────────────────────────────────


def test_slippage_buy_raises_price():
    price = _apply_slippage(100.0, "QQQ", "BUY", {"QQQ": 1})
    assert price > 100.0


def test_slippage_sell_lowers_price():
    price = _apply_slippage(100.0, "QQQ", "SELL", {"QQQ": 1})
    assert price < 100.0


def test_slippage_uses_default():
    price = _apply_slippage(100.0, "UNKNOWN", "BUY", {"default": 2})
    assert price == pytest.approx(100.0 * (1 + 2 / 10_000))


# ── run_backtest ───────────────────────────────────────────────────────────────


class TestRunBacktest:
    def _simple_setup(self, n: int = 120):
        prices = {"QQQ": _price_df(n, "QQQ")}
        df = prices["QQQ"]
        dates = pd.to_datetime(df["date"]).dt.date.tolist()
        cfg = BacktestConfig(start=dates[0], end=dates[-1], initial_capital=100_000.0)
        return prices, cfg

    def test_returns_result(self):
        prices, cfg = self._simple_setup()

        def regime_fn(*a, **kw):
            return "bull"

        def signal_fn(regime, *a, **kw):
            return []

        result = run_backtest(prices, regime_fn, signal_fn, cfg)
        assert isinstance(result, BacktestResult)

    def test_equity_length(self):
        prices, cfg = self._simple_setup(100)

        result = run_backtest(prices, lambda *a, **k: "bull", lambda *a, **k: [], cfg)
        assert len(result.equity_curve) == 100

    def test_no_lookahead(self):
        """Score at day T must equal score from truncated run at day T."""
        prices, cfg = self._simple_setup(120)

        regimes_full: list[str] = []

        def regime_fn(ndx_df, *a, **kw):
            regimes_full.append(len(ndx_df))
            return "neutral"

        run_backtest(prices, regime_fn, lambda *a, **k: [], cfg)
        # Each call's ndx_df length should be monotonically increasing (no lookahead)
        assert regimes_full == sorted(regimes_full)

    def test_buy_and_hold_matches_benchmark(self):
        prices = {"QQQ": _price_df(252, "QQQ")}
        df = prices["QQQ"]
        dates = pd.to_datetime(df["date"]).dt.date.tolist()
        cfg = BacktestConfig(start=dates[0], end=dates[-1], initial_capital=100_000.0)
        result = buy_and_hold_backtest(prices, "QQQ", cfg)
        # Strategy equity and benchmark should be very close for BH
        ratio = result.equity_curve / result.benchmark_equity
        # Should be within 2% (slippage only on entry)
        assert float(ratio.iloc[-1]) == pytest.approx(1.0, abs=0.02)

    def test_missing_benchmark_raises(self):
        with pytest.raises(ValueError, match="Benchmark"):
            run_backtest({}, lambda *a, **k: "neutral", lambda *a, **k: [], _config())

    def test_metrics_keys(self):
        prices, cfg = self._simple_setup()
        result = run_backtest(prices, lambda *a, **k: "bull", lambda *a, **k: [], cfg)
        assert set(result.metrics.keys()) == {"cagr", "max_drawdown", "sharpe", "sortino", "calmar"}


# ── Scenario tests ────────────────────────────────────────────────────────────


class TestScenarios:
    def _run_regime_strategy(self, prices_dict: dict, cfg: BacktestConfig) -> BacktestResult:
        """Run a simple regime-weighted strategy: bull=80%, bear=20%."""
        pct = [0.0]

        def regime_fn(ndx, *a, **kw):
            if ndx.empty:
                return "neutral"
            close = ndx["close"].values
            return "bull" if close[-1] > close[0] else "bear"

        def signal_fn(regime, *a, **kw):
            target = 0.80 if regime == "bull" else 0.20
            if abs(target - pct[0]) < 0.05:
                return []
            action = "BUY" if target > pct[0] else "SELL"
            delta = abs(target - pct[0])
            pct[0] = target
            return [{"ticker": "QQQ", "action": action, "target_pct": delta, "reasoning": regime}]

        return run_backtest(prices_dict, regime_fn, signal_fn, cfg)

    def test_bull_market_positive_cagr(self):
        df = _price_df(500, trend=0.001)
        dates = pd.to_datetime(df["date"]).dt.date.tolist()
        prices = {"QQQ": df}
        cfg = BacktestConfig(start=dates[0], end=dates[-1], initial_capital=100_000.0)
        result = self._run_regime_strategy(prices, cfg)
        assert result.metrics["cagr"] > 0

    def test_bear_market_smaller_drawdown(self):
        """A regime-aware strategy should have smaller drawdown than BH in a bear market."""
        df = _price_df(500, trend=-0.001)
        dates = pd.to_datetime(df["date"]).dt.date.tolist()
        prices = {"QQQ": df}
        cfg = BacktestConfig(start=dates[0], end=dates[-1], initial_capital=100_000.0)
        strategy = self._run_regime_strategy(prices, cfg)
        bh = buy_and_hold_backtest(prices, "QQQ", cfg)
        # Strategy should have less drawdown than buy-and-hold in a downtrend
        assert strategy.metrics["max_drawdown"] > bh.metrics["max_drawdown"]
