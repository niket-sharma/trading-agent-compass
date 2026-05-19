"""Entry point for Streamlit Community Cloud."""

import streamlit as st

st.set_page_config(
    page_title="Trading Agent",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Password gate disabled — re-enable by uncommenting the block below
# and replacing the two lines after it with: if _require_password():
st.session_state.authed = True

# import secrets as stdlib_secrets
# import time
#
# def _require_password() -> bool:
#     if st.session_state.get("authed"):
#         return True
#     st.title("Trading Agent")
#     st.caption("Enter the access password to continue.")
#     pw = st.text_input("Password", type="password", key="pw_input")
#     if st.button("Enter", type="primary"):
#         expected = st.secrets.get("APP_PASSWORD", "")
#         if expected and stdlib_secrets.compare_digest(pw.encode(), expected.encode()):
#             st.session_state.authed = True
#             st.rerun()
#         else:
#             time.sleep(1.0)
#             st.error("Incorrect password.")
#     return False

from tradeagent.ui.sidebar import render_sidebar
from tradeagent.ui.pages.dashboard import render_dashboard

render_sidebar()
render_dashboard()
