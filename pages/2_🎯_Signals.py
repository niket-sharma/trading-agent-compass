"""Signals page — today's recommended trades per bucket."""
from __future__ import annotations

import streamlit as st

from tradeagent.ui.freshness import render_freshness_banner
from tradeagent.ui.sidebar import render_sidebar

st.set_page_config(page_title="Signals — Trading Agent", page_icon="🎯", layout="wide")

if not st.session_state.get("authed"):
    st.stop()

render_sidebar()
render_freshness_banner()

st.title("🎯 Daily Signals")

profile_name = st.session_state.get("profile", "moderate")
openai_key = st.session_state.get("openai_key")

if not openai_key:
    st.info("💡 Sentiment scoring skipped — add an OpenAI key in the sidebar for sentiment-aware signals.")


@st.cache_data(ttl=900)
def _compute_signals(profile_name: str, openai_key: str | None) -> dict:
    """Compute today's signals. Returns a serializable dict."""
    import pandas as pd

    from tradeagent.analysis.regime import Regime, classify_regime
    from tradeagent.analysis.sentiment import aggregate_ticker_sentiment
    from tradeagent.analysis.technical import compute_technical_score
    from tradeagent.config import get_config
    from tradeagent.data.store import load_macro, load_news, load_prices
    from tradeagent.strategy.allocation import compute_target_weights
    from tradeagent.strategy.safety import apply_safety_overlays
    from tradeagent.strategy.signals import generate_signals

    cfg = get_config()
    profile = cfg.profiles.get(profile_name)
    if profile is None:
        return {"error": f"Profile '{profile_name}' not found."}

    # Load price data
    ndx = load_prices("QQQ")
    vix_df = load_prices("^VIX")
    if vix_df.empty:
        vix_macro = load_macro("VIX")
        vix_df = vix_macro.rename(columns={"value": "close"}) if not vix_macro.empty else pd.DataFrame()

    macro = {s: load_macro(s) for s in ["DGS10", "DGS2"]}
    breadth = {t: load_prices(t) for t in cfg.universe.single_names}

    if ndx.empty:
        return {"error": "No price data. Run `tradectl refresh all` first."}

    # Sentiment (optional)
    sent_score = None
    if openai_key:
        cache = st.session_state.setdefault("sentiment_cache", {})
        scores = []
        for t in cfg.universe.all_tickers:
            arts = load_news(t, days=7)
            s, _conf, cost = aggregate_ticker_sentiment(arts, api_key=openai_key, session_cache=cache)
            st.session_state["session_cost_usd"] = st.session_state.get("session_cost_usd", 0.0) + cost
            if not arts.empty:
                scores.append(s)
        if scores:
            sent_score = sum(scores) / len(scores)

    # Regime
    reading = classify_regime(ndx, vix_df, macro, breadth, sentiment_score=sent_score)

    # VIX level for safety overlay
    vix_level = 20.0
    if not vix_df.empty and "close" in vix_df.columns:
        vix_level = float(vix_df["close"].iloc[-1])

    # Technical scores per ticker
    all_prices = {t: load_prices(t) for t in cfg.universe.all_tickers}
    tech_scores: dict[str, float] = {}
    for t, df in all_prices.items():
        if not df.empty:
            sc = compute_technical_score(df)
            tech_scores[t] = sc["composite"]

    latest_prices: dict[str, float] = {
        t: float(df["close"].iloc[-1]) for t, df in all_prices.items() if not df.empty
    }

    # Allocation weights
    target_weights = compute_target_weights(reading.regime, profile, ema_alpha=1.0)

    # Assume current weights = 0 (we don't track portfolio state in v1 UI)
    current_weights: dict[str, float] = {k: 0.0 for k in target_weights}

    # Generate signals
    raw_signals = generate_signals(
        reading.regime.value,
        target_weights,
        current_weights,
        tech_scores,
        latest_prices,
        portfolio_value=100_000.0,
    )

    # Safety overlays
    signals = apply_safety_overlays(
        raw_signals,
        vix_level=vix_level,
        regime_score=reading.score,
    )

    return {
        "regime": reading.regime.value,
        "regime_score": reading.score,
        "regime_age": reading.regime_age_days,
        "sentiment_included": reading.sentiment_included,
        "target_weights": target_weights,
        "signals": [
            {
                "action": s.action,
                "ticker": s.ticker,
                "bucket": s.bucket,
                "target_pct": s.target_pct,
                "limit_price": s.limit_price,
                "urgency": s.urgency,
                "confidence": s.confidence,
                "reasoning": s.reasoning,
            }
            for s in signals
        ],
    }


if st.button("🔄 Refresh Signals", type="primary"):
    _compute_signals.clear()
    st.rerun()

with st.spinner("Computing signals..."):
    data = _compute_signals(profile_name, openai_key)

if "error" in data:
    st.error(data["error"])
    st.stop()

# ── Regime header ─────────────────────────────────────────────────────────────

REGIME_ICONS = {
    "strong_bull": "🟢",
    "bull": "🟩",
    "neutral": "🟨",
    "bear": "🟧",
    "strong_bear": "🔴",
}
regime = data["regime"]
icon = REGIME_ICONS.get(regime, "❓")
label = regime.replace("_", " ").title()

col1, col2, col3 = st.columns(3)
col1.metric("Current Regime", f"{icon} {label}")
col2.metric("Regime Score", f"{data['regime_score']:+.3f}")
col3.metric("Regime Age", f"{data['regime_age']} trading days")

st.divider()

# ── Signals table ─────────────────────────────────────────────────────────────

signals = data["signals"]
if not signals:
    st.success("✅ Portfolio is already aligned with the current regime. No trades needed.")
else:
    st.subheader(f"Recommended Actions — {profile_name.title()} Profile")
    st.caption("*Target % is the fraction of total portfolio value to move.*")

    URGENCY_COLOR = {"high": "🔴", "medium": "🟡", "low": "🟢"}
    ACTION_COLOR = {"BUY": "🟢", "SELL": "🔴", "HOLD": "⬜"}

    for sig in signals:
        urgency_icon = URGENCY_COLOR.get(sig["urgency"], "")
        action_icon = ACTION_COLOR.get(sig["action"], "")
        limit = f"~${sig['limit_price']:.2f}" if sig["limit_price"] else "market"

        with st.expander(
            f"{action_icon} **{sig['action']}** {sig['ticker']} "
            f"({sig['bucket'].replace('_', ' ').title()}) — "
            f"{sig['target_pct']:.1%} of portfolio {urgency_icon}"
        ):
            col1, col2, col3 = st.columns(3)
            col1.metric("Action", sig["action"])
            col2.metric("Target Size", f"{sig['target_pct']:.1%}")
            col3.metric("Limit Price", limit)
            st.write("**Reasoning:**")
            for k, v in sig["reasoning"].items():
                st.write(f"- {k.replace('_', ' ').title()}: {v}")

st.divider()

# ── Target allocation ─────────────────────────────────────────────────────────

st.subheader("Target Allocation")
import pandas as pd  # noqa: E402

weights = data["target_weights"]
w_df = pd.DataFrame(
    {"Bucket": list(weights.keys()), "Target Weight": list(weights.values())}
).set_index("Bucket")
st.bar_chart(w_df, use_container_width=True)
