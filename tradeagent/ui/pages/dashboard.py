"""Dashboard page — main landing page after login."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from tradeagent.config import get_config
from tradeagent.data.store import load_prices
from tradeagent.ui.freshness import render_freshness_banner


@st.cache_data(ttl=3600)
def _load_prices_cached(ticker: str) -> pd.DataFrame:
    return load_prices(ticker)


@st.cache_data(ttl=3600)
def _quick_regime() -> dict:
    """Compute regime for the dashboard card (no sentiment, fast)."""
    from tradeagent.analysis.regime import classify_regime
    from tradeagent.data.store import load_macro

    ndx = load_prices("QQQ")
    vix_macro = load_macro("VIX")
    vix = vix_macro.rename(columns={"value": "close"}) if not vix_macro.empty else pd.DataFrame()
    macro = {s: load_macro(s) for s in ["DGS10", "DGS2"]}

    if ndx.empty:
        return {}
    reading = classify_regime(ndx, vix, macro, {})
    return {"regime": reading.regime.value, "score": reading.score}


def render_dashboard() -> None:
    """Render the main dashboard page."""
    render_freshness_banner()

    st.title("Trading Agent — Personal v1")
    st.caption("Advisory only. Not financial advice. Leveraged ETFs carry significant risk.")

    cfg = get_config()
    all_tickers = cfg.universe.all_tickers

    # ── Ticker chart ─────────────────────────────────────────────────────
    col1, col2 = st.columns([2, 1])
    with col1:
        selected_ticker = st.selectbox("Select ticker", options=all_tickers, index=0)
    with col2:
        lookback_years = st.selectbox(
            "Lookback", options=[1, 2, 3, 5, 10], index=0, format_func=lambda x: f"{x}Y"
        )

    df = _load_prices_cached(selected_ticker)

    if df.empty:
        st.warning(
            f"No price data for {selected_ticker}. "
            "Run `python scripts/refresh_static_data.py` to populate data/."
        )
    else:
        df["date"] = pd.to_datetime(df["date"], utc=True)
        cutoff = pd.Timestamp.now(tz="UTC") - pd.DateOffset(years=lookback_years)
        df_plot = df[df["date"] >= cutoff].copy()

        st.subheader(f"{selected_ticker} — Adjusted Close")
        chart_df = df_plot.set_index("date")[["adj_close"]].rename(columns={"adj_close": "Price"})
        st.line_chart(chart_df)
        last_date = df_plot["date"].max().date()
        last_price = float(df_plot["adj_close"].iloc[-1])
        st.caption(
            f"{len(df_plot):,} rows · Last date: {last_date} · Last adj close: ${last_price:.2f}"
        )

    # ── Summary cards ─────────────────────────────────────────────────────
    st.divider()
    c1, c2, c3 = st.columns(3)

    REGIME_ICONS = {
        "strong_bull": "🟢", "bull": "🟩", "neutral": "🟨",
        "bear": "🟧", "strong_bear": "🔴",
    }

    with c1, st.container(border=True):
        st.markdown("**📈 Regime**")
        regime_data = _quick_regime()
        if regime_data:
            label = regime_data["regime"].replace("_", " ").title()
            icon = REGIME_ICONS.get(regime_data["regime"], "❓")
            st.metric(label=f"{icon} {label}", value=f"{regime_data['score']:+.3f}")
            st.caption("→ [Regime page](./3_📈_Regime)")
        else:
            st.info("No data. Refresh static data first.")

    with c2, st.container(border=True):
        st.markdown("**🎯 Signals**")
        profile = st.session_state.get("profile", "moderate")
        st.write(f"Profile: **{profile.title()}**")
        st.caption("→ [Signals page](./2_🎯_Signals) for today's recommendations")

    with c3, st.container(border=True):
        st.markdown("**🧪 Backtest**")
        st.write("Walk-forward 2015-2024")
        st.caption("→ [Backtest page](./4_🧪_Backtest) to run simulation")
