"""Sidebar: profile picker, OpenAI key input, session cost counter, sign-out."""

from __future__ import annotations

import streamlit as st

from tradeagent.config import get_config


def render_sidebar() -> None:
    """Render the persistent sidebar. Call after auth check."""
    cfg = get_config()
    profile_names = sorted(cfg.profiles.keys())

    with st.sidebar:
        st.title("Trading Agent")
        st.caption("Personal v1 — Advisory only")
        st.divider()

        # ── Profile selector ──────────────────────────────────────────────
        st.subheader("Risk Profile")
        current_profile = st.session_state.get("profile_name", "moderate")
        if current_profile not in profile_names:
            current_profile = "moderate"

        selected = st.selectbox(
            "Profile",
            options=profile_names,
            index=profile_names.index(current_profile),
            key="profile_selector",
            label_visibility="collapsed",
        )
        st.session_state.profile_name = selected

        if selected in cfg.profiles:
            prof = cfg.profiles[selected]
            st.caption(
                f"Risk {prof.risk_level}/10 · Max {prof.max_leverage}x leverage · "
                f"{prof.trading_intensity.capitalize()} trading"
            )

        st.divider()

        # ── OpenAI key ────────────────────────────────────────────────────
        st.subheader("OpenAI Key")
        key_set = bool(st.session_state.get("openai_key"))

        if key_set:
            st.success("✓ Key set")
            if st.button("Clear key", key="clear_openai_key"):
                st.session_state.openai_key = ""
                st.rerun()
        else:
            key_input = st.text_input(
                "Paste your OpenAI API key",
                type="password",
                key="openai_key_input",
                placeholder="sk-...",
                label_visibility="collapsed",
            )
            if key_input:
                st.session_state.openai_key = key_input
                st.rerun()
            st.caption("Optional: enables sentiment-aware signals")

        # Session cost counter (updated in Phase 1 after OpenAI calls)
        if "session_cost_usd" not in st.session_state:
            st.session_state.session_cost_usd = 0.0

        cost = st.session_state.session_cost_usd
        st.caption(f"Session spend: ${cost:.4f}")

        st.divider()

        # ── Sign out ──────────────────────────────────────────────────────
        if st.button("Sign out", key="sign_out"):
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()
