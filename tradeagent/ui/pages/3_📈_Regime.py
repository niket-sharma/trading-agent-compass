"""Regime page — current market regime, component scores, and history."""
from __future__ import annotations

import streamlit as st

from tradeagent.ui.freshness import render_freshness_banner
from tradeagent.ui.sidebar import render_sidebar

st.set_page_config(page_title="Regime — Trading Agent", page_icon="📈", layout="wide")

if not st.session_state.get("authed"):
    st.stop()

render_sidebar()
render_freshness_banner()

st.title("📈 Market Regime")

# ── Load data ─────────────────────────────────────────────────────────────────


@st.cache_data(ttl=3600)
def _load_regime_inputs() -> tuple:
    """Load all DataFrames needed for regime classification."""
    import pandas as pd

    from tradeagent.config import get_config
    from tradeagent.data.store import load_macro, load_prices

    cfg = get_config()
    ndx = load_prices("QQQ")  # proxy for NDX
    vix = load_prices("^VIX") if not load_prices("^VIX").empty else pd.DataFrame({"close": []})

    # Use VIX from macro store if not in prices
    if vix.empty:
        vix_macro = load_macro("VIX")
        if not vix_macro.empty:
            vix = vix_macro.rename(columns={"value": "close"})

    macro = {sid: load_macro(sid) for sid in ["DGS10", "DGS2"]}
    breadth = {t: load_prices(t) for t in cfg.universe.single_names}
    return ndx, vix, macro, breadth


@st.cache_data(ttl=3600)
def _compute_regime(openai_key: str | None) -> dict:
    """Compute regime reading and return a serializable dict."""
    from tradeagent.analysis.regime import classify_regime
    from tradeagent.analysis.sentiment import aggregate_ticker_sentiment
    from tradeagent.config import get_config
    from tradeagent.data.store import load_news

    ndx, vix, macro, breadth = _load_regime_inputs()

    if ndx.empty:
        return {}

    # Sentiment (only if user provided a key)
    sent_score = None
    total_cost = 0.0
    if openai_key:
        cache = st.session_state.setdefault("sentiment_cache", {})
        cfg = get_config()
        scores = []
        for ticker in cfg.universe.all_tickers:
            articles = load_news(ticker, days=7)
            s, _conf, cost = aggregate_ticker_sentiment(
                articles, api_key=openai_key, session_cache=cache
            )
            total_cost += cost
            if articles.shape[0] > 0:
                scores.append(s)
        if scores:
            sent_score = float(sum(scores) / len(scores))
        # Update session cost counter
        st.session_state["session_cost_usd"] = (
            st.session_state.get("session_cost_usd", 0.0) + total_cost
        )

    reading = classify_regime(ndx, vix, macro, breadth, sentiment_score=sent_score)
    return {
        "date": str(reading.date),
        "regime": reading.regime.value,
        "score": reading.score,
        "components": reading.components,
        "regime_age_days": reading.regime_age_days,
        "sentiment_included": reading.sentiment_included,
        "sentiment_cost": total_cost,
    }


# ── Render ───────────────────────────────────────────────────────────────────

openai_key = st.session_state.get("openai_key")

col1, col2 = st.columns([2, 3])

with col1:
    if st.button("🔄 Compute Regime", type="primary"):
        _compute_regime.clear()
        st.rerun()

    if not openai_key:
        st.info("💡 Add an OpenAI key in the sidebar for sentiment-aware regime scoring.")

with col2:
    st.write("")

with st.spinner("Computing regime..."):
    result = _compute_regime(openai_key)

if not result:
    st.warning("No price data found. Run `tradectl refresh all` to populate data/.")
    st.stop()

# ── Regime card ───────────────────────────────────────────────────────────────

REGIME_COLORS = {
    "strong_bull": "🟢",
    "bull": "🟩",
    "neutral": "🟨",
    "bear": "🟧",
    "strong_bear": "🔴",
}
REGIME_LABELS = {
    "strong_bull": "Strong Bull",
    "bull": "Bull",
    "neutral": "Neutral",
    "bear": "Bear",
    "strong_bear": "Strong Bear",
}

regime = result["regime"]
icon = REGIME_COLORS.get(regime, "❓")
label = REGIME_LABELS.get(regime, regime.replace("_", " ").title())
score = result["score"]
age = result["regime_age_days"]

col1, col2, col3 = st.columns(3)
col1.metric("Regime", f"{icon} {label}")
col2.metric("Composite Score", f"{score:+.3f}")
col3.metric("Regime Age", f"{age} trading days")

if result.get("sentiment_included"):
    st.caption(
        f"Sentiment included (estimated cost this refresh: ${result['sentiment_cost']:.4f})"
    )
else:
    st.caption("Sentiment excluded — add an OpenAI key for sentiment-aware scoring.")

st.divider()

# ── Component scores bar chart ────────────────────────────────────────────────

st.subheader("Component Scores")
components = result["components"]

import pandas as pd  # noqa: E402

comp_df = pd.DataFrame(
    {"Component": list(components.keys()), "Score": list(components.values())}
).set_index("Component")

st.bar_chart(comp_df, use_container_width=True)

with st.expander("Component explanations"):
    st.markdown(
        """
| Component | Measures |
|---|---|
| trend_slope | 200d OLS slope of NDX log-price, annualized |
| ma_cross | 50d vs 200d MA: golden cross (+1) / death cross (-1) |
| vix_level | VIX absolute level (>35 → strong bear, <15 → bull) |
| vix_change_20d | 20-day change in VIX (rising = bearish) |
| drawdown | NDX drawdown from 52-week high |
| breadth | % of single-name universe above their 50d MA |
| yield_curve | 10y − 2y Treasury spread (inversion → bear) |
| sentiment | Aggregate news sentiment from OpenAI scoring |
"""
    )

st.divider()

# ── Price chart with regime context ──────────────────────────────────────────

st.subheader("QQQ Price (last 252 trading days)")

from tradeagent.data.store import load_prices  # noqa: E402

qqq = load_prices("QQQ")
if not qqq.empty:
    recent = qqq.tail(252).set_index("date")["close"]
    st.line_chart(recent, use_container_width=True)
