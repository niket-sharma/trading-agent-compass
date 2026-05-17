"""Freshness banner: shows data date and last-refresh timestamp on every page.

Phase 0: data date only; last-refresh shows "?" (stub).
Phase 1: authenticated GitHub API call fills in the timestamp.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import streamlit as st

from tradeagent.data.store import get_latest_data_date


@st.cache_data(ttl=900)  # 15 minutes
def _fetch_last_workflow_run() -> datetime | None:
    """Query GitHub for the most recent successful run of the refresh workflow.

    Phase 0: always returns None. The banner handles None gracefully (shows '?').
    Phase 1 implements this with an authenticated GitHub REST API call using
    st.secrets['GITHUB_TOKEN'] — required because the repo is private.
    """
    return None


def _trading_days_between(a: pd.Timestamp, b: pd.Timestamp) -> int:
    """Count US weekdays (Mon-Fri) between two dates. Holidays ignored in v1."""
    return max(0, len(pd.bdate_range(start=a, end=b)) - 1)


def render_freshness_banner() -> None:
    """Render the freshness banner at the top of every page.

    Shows:
      📊 Market data through YYYY-MM-DD (Day close) · Last refresh: Nh ago | ?

    Yellow warning if data is more than 2 US trading days stale.
    """
    latest = get_latest_data_date()
    last_run = _fetch_last_workflow_run()
    now = datetime.now(UTC)

    weekday = pd.Timestamp(latest).day_name()[:3]
    data_str = f"Market data through **{latest:%Y-%m-%d}** ({weekday} close)"

    if last_run is None:
        refresh_str = "Last refresh: ?"
    else:
        delta = now - last_run
        hours = int(delta.total_seconds() // 3600)
        if hours < 24:
            refresh_str = f"Last refresh: {hours}h ago"
        else:
            refresh_str = f"Last refresh: {delta.days}d ago"

    today_utc = pd.Timestamp(now.date())
    staleness_days = _trading_days_between(pd.Timestamp(latest), today_utc)
    stale = staleness_days > 2

    msg = f"📊 {data_str} · {refresh_str}"
    if stale:
        st.warning(f"⚠️ {msg} — Data may be stale. Owner: check the Actions tab.")
    else:
        st.info(msg)
        if last_run is None:
            st.caption(
                "i Live refresh timestamp coming in Phase 1 - requires authenticated "
                "API call for private repos."
            )
