"""Backtest page — walk-forward simulation."""
from __future__ import annotations

import streamlit as st

from tradeagent.ui.freshness import render_freshness_banner
from tradeagent.ui.sidebar import render_sidebar

st.set_page_config(page_title="Backtest — Trading Agent", page_icon="🧪", layout="wide")

if not st.session_state.get("authed"):
    st.stop()

render_sidebar()
render_freshness_banner()

st.title("🧪 Backtest")

# ── Configuration ─────────────────────────────────────────────────────────────

with st.form("backtest_config"):
    col1, col2, col3 = st.columns(3)
    with col1:
        start_date = st.date_input("Start date", value=None, min_value=None)
        if start_date is None:
            from datetime import date
            start_date = date(2015, 1, 1)
    with col2:
        end_date = st.date_input("End date", value=None)
        if end_date is None:
            from datetime import date
            end_date = date(2024, 12, 31)
    with col3:
        capital = st.number_input("Initial capital ($)", min_value=1000, value=100_000, step=1000)

    submitted = st.form_submit_button("▶ Run Backtest", type="primary")


@st.cache_data(ttl=0)  # cache keyed by arguments below
def _run_backtest_cached(start_str: str, end_str: str, capital: float, profile_name: str) -> dict:
    """Run the full strategy backtest and return a serializable result dict."""
    from datetime import date as date_cls

    import pandas as pd

    from tradeagent.analysis.regime import Regime, classify_regime
    from tradeagent.backtest.engine import BacktestConfig, run_backtest
    from tradeagent.config import get_config
    from tradeagent.data.store import load_macro, load_prices

    cfg = get_config()
    start = date_cls.fromisoformat(start_str)
    end = date_cls.fromisoformat(end_str)

    # Load all price data
    all_tickers = cfg.universe.all_tickers + [cfg.universe.ndx_symbol, "^VIX"]
    prices: dict = {}
    for t in all_tickers:
        df = load_prices(t, start=start, end=end)
        if not df.empty:
            prices[t] = df

    bench_ticker = "QQQ"
    if bench_ticker not in prices:
        return {"error": f"No price data for {bench_ticker}. Run tradectl refresh all first."}

    macro = {sid: load_macro(sid) for sid in ["DGS10", "DGS2"]}
    vix = load_prices("^VIX")
    if vix.empty:
        vix_macro = load_macro("VIX")
        vix = vix_macro.rename(columns={"value": "close"}) if not vix_macro.empty else pd.DataFrame()

    breadth = {t: load_prices(t) for t in cfg.universe.single_names if t in prices}

    # Load profile for allocation weights
    profile = cfg.profiles.get(profile_name)

    # Regime function
    def regime_fn(ndx_df, vix_df, macro_dict, breadth_dict, as_of):
        if ndx_df.empty:
            return Regime.NEUTRAL.value
        reading = classify_regime(ndx_df, vix_df, macro_dict, breadth_dict, as_of=as_of)
        return reading.regime.value

    # Simple signal function: weight QQQ by regime
    REGIME_WEIGHTS = {
        "strong_bull": 0.95,
        "bull": 0.80,
        "neutral": 0.60,
        "bear": 0.30,
        "strong_bear": 0.10,
    }

    last_regime = "neutral"
    invested_pct = 0.0

    def signal_fn(regime, ndx_df, portfolio_val, as_of):
        nonlocal last_regime, invested_pct
        target = REGIME_WEIGHTS.get(regime, 0.60)
        if abs(target - invested_pct) < 0.05:  # avoid micro-trades
            return []
        action = "BUY" if target > invested_pct else "SELL"
        delta_pct = abs(target - invested_pct)
        invested_pct = target
        last_regime = regime
        return [{"ticker": "QQQ", "action": action, "target_pct": delta_pct,
                 "reasoning": f"regime={regime} → target={target:.0%}"}]

    bt_config = BacktestConfig(
        start=start,
        end=end,
        initial_capital=capital,
        slippage_bps={"QQQ": 1, "QLD": 1, "TQQQ": 3, "SQQQ": 3, "default": 2},
    )

    result = run_backtest(
        prices=prices,
        regime_fn=regime_fn,
        signal_fn=signal_fn,
        config=bt_config,
        macro=macro,
        vix_prices=vix if not vix.empty else None,
        breadth_prices=breadth,
    )

    # Benchmark: QQQ buy-and-hold
    from tradeagent.backtest.engine import buy_and_hold_backtest
    bench_result = buy_and_hold_backtest(prices, "QQQ", bt_config)

    return {
        "equity": result.equity_curve.to_dict(),
        "benchmark": bench_result.equity_curve.to_dict(),
        "metrics": result.metrics,
        "bench_metrics": bench_result.metrics,
        "trades_count": len(result.trades),
        "tax": result.tax_summary,
    }


if submitted:
    profile_name = st.session_state.get("profile", "moderate")
    bt_key = f"{start_date}_{end_date}_{capital}_{profile_name}"

    if bt_key not in st.session_state.get("backtest_results", {}):
        with st.spinner("Running backtest… this may take 15-30 seconds."):
            bt = _run_backtest_cached(str(start_date), str(end_date), float(capital), profile_name)
            st.session_state.setdefault("backtest_results", {})[bt_key] = bt
    else:
        bt = st.session_state["backtest_results"][bt_key]

    if "error" in bt:
        st.error(bt["error"])
        st.stop()

    import pandas as pd

    equity = pd.Series(bt["equity"])
    equity.index = pd.to_datetime(equity.index)
    bench = pd.Series(bt["benchmark"])
    bench.index = pd.to_datetime(bench.index)

    # ── Metrics ──────────────────────────────────────────────────────────
    m = bt["metrics"]
    bm = bt["bench_metrics"]

    st.subheader("📊 Performance vs QQQ Buy-and-Hold")
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("CAGR", f"{m['cagr']:.1%}", delta=f"{m['cagr']-bm['cagr']:+.1%} vs bench")
    col2.metric("Max Drawdown", f"{m['max_drawdown']:.1%}", delta=f"{m['max_drawdown']-bm['max_drawdown']:+.1%} vs bench", delta_color="inverse")
    col3.metric("Sharpe", f"{m['sharpe']:.2f}", delta=f"{m['sharpe']-bm['sharpe']:+.2f} vs bench")
    col4.metric("Sortino", f"{m['sortino']:.2f}")
    col5.metric("Trades", str(bt["trades_count"]))

    st.divider()

    # ── Equity curve ─────────────────────────────────────────────────────
    st.subheader("Equity Curve")
    combined = pd.DataFrame({"Strategy": equity, "QQQ B&H": bench})
    st.line_chart(combined, use_container_width=True)

    # ── Drawdown ─────────────────────────────────────────────────────────
    st.subheader("Strategy Drawdown")
    dd = (equity - equity.cummax()) / equity.cummax()
    st.area_chart(dd, use_container_width=True)

    # ── Tax summary ───────────────────────────────────────────────────────
    with st.expander("Tax summary"):
        tax = bt["tax"]
        st.write(f"Short-term gains: **${tax['st_gains']:,.0f}**")
        st.write(f"Long-term gains: **${tax['lt_gains']:,.0f}**")

else:
    st.info("Configure the date range and click **Run Backtest** to start.")
    st.caption(
        "The backtest uses the regime-weighted QQQ strategy: allocation to QQQ follows "
        "the current regime (Strong Bull → 95%, Bear → 30%). Phase 3 wires in full "
        "multi-bucket signals."
    )
