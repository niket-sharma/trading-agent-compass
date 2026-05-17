"""Dashboard page — main content for Phase 0.

Shows a freshness banner, ticker price chart, and placeholder cards for
regime/signals/backtest (implemented in later phases).
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from tradeagent.config import get_config
from tradeagent.data.store import load_prices
from tradeagent.ui.freshness import render_freshness_banner


@st.cache_data(ttl=3600)
def _load_prices_cached(ticker: str) -> pd.DataFrame:
    return load_prices(ticker)


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
        selected_ticker = st.selectbox(
            "Select ticker",
            options=all_tickers,
            index=0,
        )
    with col2:
        lookback_years = st.selectbox(
            "Lookback",
            options=[1, 2, 3, 5, 10],
            index=0,
            format_func=lambda x: f"{x}Y",
        )

    df = _load_prices_cached(selected_ticker)

    if df.empty:
        st.warning(
            f"No price data for {selected_ticker}. "
            "Run `python scripts/refresh_static_data.py` to populate data/."
        )
        return

    df["date"] = pd.to_datetime(df["date"], utc=True)
    cutoff = pd.Timestamp.now(tz="UTC") - pd.DateOffset(years=lookback_years)
    df_plot = df[df["date"] >= cutoff].copy()

    if df_plot.empty:
        st.warning(f"No data for {selected_ticker} in the last {lookback_years} year(s).")
        return

    st.subheader(f"{selected_ticker} — Adjusted Close")
    chart_df = df_plot.set_index("date")[["adj_close"]].rename(columns={"adj_close": "Price"})
    st.line_chart(chart_df)

    last_date = df_plot["date"].max().date()
    last_price = df_plot["adj_close"].iloc[-1]
    st.caption(
        f"Loaded {len(df_plot):,} rows for {selected_ticker} · "
        f"Last date: {last_date} · Last adj close: ${last_price:.2f}"
    )

    # ── Placeholder cards ─────────────────────────────────────────────────
    st.divider()
    c1, c2, c3 = st.columns(3)
    with c1, st.container(border=True):
        st.markdown("**Regime**")
        st.caption("Coming in Phase 1")
        st.info("—", icon="📈")
    with c2, st.container(border=True):
        st.markdown("**Signals**")
        st.caption("Coming in Phase 3")
        st.info("—", icon="🎯")
    with c3, st.container(border=True):
        st.markdown("**Backtest**")
        st.caption("Coming in Phase 2")
        st.info("—", icon="🧪")
