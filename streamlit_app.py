"""Entry point for Streamlit Community Cloud.

Password-gates access before rendering any other UI. Credentials are compared
using constant-time comparison to resist timing attacks.
"""

import secrets as stdlib_secrets
import time

import streamlit as st

st.set_page_config(
    page_title="Trading Agent",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _require_password() -> bool:
    """Return True iff the session is authenticated."""
    if st.session_state.get("authed"):
        return True

    st.title("Trading Agent")
    st.caption("Enter the access password to continue.")

    pw = st.text_input("Password", type="password", key="pw_input")
    if st.button("Enter", type="primary"):
        expected = st.secrets.get("APP_PASSWORD", "")
        if expected and stdlib_secrets.compare_digest(pw.encode(), expected.encode()):
            st.session_state.authed = True
            st.rerun()
        else:
            time.sleep(1.0)  # rate-limit brute-force attempts
            st.error("Incorrect password.")

    return False


if _require_password():
    from tradeagent.ui.sidebar import render_sidebar
    from tradeagent.ui.pages.dashboard import render_dashboard

    render_sidebar()
    render_dashboard()
