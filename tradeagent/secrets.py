"""Secret resolution helper.

Resolution order:
  1. st.session_state[name]  — only if allow_session=True (used for OPENAI_API_KEY)
  2. st.secrets[name]        — owner-configured (APP_PASSWORD, TIINGO_API_KEY, etc.)
  3. os.environ[name]        — local dev fallback
  4. Returns None            — caller decides if that's an error

Keys are never logged or echoed back to users.
"""

from __future__ import annotations

import os


def get_secret(name: str, *, allow_session: bool = True) -> str | None:
    """Resolve a secret by name.

    Args:
        name: Secret key name (e.g. "TIINGO_API_KEY").
        allow_session: If True and Streamlit is running, check st.session_state
            first. Set to False for secrets the user never provides (e.g. TIINGO).

    Returns:
        The secret value, or None if not found anywhere.
    """
    # 1. Session state (visitor-pasted keys, e.g. OPENAI_API_KEY)
    if allow_session:
        try:
            import streamlit as st

            val = st.session_state.get(name)
            if val:
                return str(val)
        except Exception:
            pass

    # 2. st.secrets (owner-configured in Streamlit Cloud dashboard)
    try:
        import streamlit as st

        val = st.secrets.get(name)
        if val:
            return str(val)
    except Exception:
        pass

    # 3. Environment variable (local dev)
    val = os.environ.get(name)
    if val:
        return val

    return None


def require_secret(name: str, *, allow_session: bool = True) -> str:
    """Like get_secret but raises a descriptive error if not found."""
    val = get_secret(name, allow_session=allow_session)
    if not val:
        raise OSError(
            f"Required secret {name!r} not found. "
            "Set it in Streamlit Cloud secrets, local .streamlit/secrets.toml, or env."
        )
    return val
