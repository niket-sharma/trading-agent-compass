"""Tests for the freshness banner logic."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pandas as pd


def test_trading_days_between_same_day():
    from tradeagent.ui.freshness import _trading_days_between

    today = pd.Timestamp("2024-01-08")  # Monday
    assert _trading_days_between(today, today) == 0


def test_trading_days_between_two_weekdays():
    from tradeagent.ui.freshness import _trading_days_between

    mon = pd.Timestamp("2024-01-08")  # Monday
    wed = pd.Timestamp("2024-01-10")  # Wednesday
    assert _trading_days_between(mon, wed) == 2


def test_trading_days_skips_weekend():
    from tradeagent.ui.freshness import _trading_days_between

    fri = pd.Timestamp("2024-01-05")  # Friday
    mon = pd.Timestamp("2024-01-08")  # Monday
    # Friday → Monday is 1 trading day (Monday is the next open day)
    assert _trading_days_between(fri, mon) == 1


def test_fetch_last_workflow_run_is_none_in_phase0():
    """Phase 0 stub always returns None."""
    # Clear the cache first
    from tradeagent.ui import freshness as freshness_mod

    freshness_mod._fetch_last_workflow_run.clear()
    result = freshness_mod._fetch_last_workflow_run()
    assert result is None


def test_render_freshness_banner_not_stale(tmp_data_dir, sample_price_df):
    """Banner shows info (not warning) when data is current."""
    from tradeagent.data.store import save_prices

    save_prices("QQQ", sample_price_df)  # today's date in fixture

    info_calls = []
    warning_calls = []

    with (
        patch("streamlit.info", side_effect=lambda msg, **kw: info_calls.append(msg)),
        patch("streamlit.warning", side_effect=lambda msg, **kw: warning_calls.append(msg)),
        patch("streamlit.caption"),
        patch("tradeagent.ui.freshness._fetch_last_workflow_run", return_value=None),
    ):
        from tradeagent.ui.freshness import render_freshness_banner

        render_freshness_banner()

    assert len(warning_calls) == 0
    assert len(info_calls) == 1
    assert "Market data through" in info_calls[0]


def test_render_freshness_banner_stale(tmp_data_dir):
    """Banner shows warning when data is >2 trading days stale."""
    import pandas as pd

    from tradeagent.data.store import save_prices

    # Make stale data: 10 trading days ago
    old_date = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=14)
    stale_df = pd.DataFrame(
        {
            "date": [old_date],
            "open": [100.0],
            "high": [101.0],
            "low": [99.0],
            "close": [100.5],
            "adj_close": [100.5],
            "volume": [1_000_000],
        }
    )
    save_prices("QQQ", stale_df)

    warning_calls = []

    with (
        patch("streamlit.warning", side_effect=lambda msg, **kw: warning_calls.append(msg)),
        patch("streamlit.info"),
        patch("streamlit.caption"),
        patch("tradeagent.ui.freshness._fetch_last_workflow_run", return_value=None),
    ):
        from tradeagent.ui.freshness import render_freshness_banner

        render_freshness_banner()

    assert len(warning_calls) == 1
    assert "stale" in warning_calls[0].lower()


def test_render_freshness_banner_with_last_run_timestamp(tmp_data_dir, sample_price_df):
    """When _fetch_last_workflow_run returns a datetime, banner shows 'Nh ago'."""
    from tradeagent.data.store import save_prices

    save_prices("QQQ", sample_price_df)

    six_hours_ago = datetime.now(UTC) - timedelta(hours=6)
    info_calls = []

    with (
        patch("streamlit.info", side_effect=lambda msg, **kw: info_calls.append(msg)),
        patch("streamlit.warning"),
        patch("streamlit.caption"),
        patch(
            "tradeagent.ui.freshness._fetch_last_workflow_run",
            return_value=six_hours_ago,
        ),
    ):
        from tradeagent.ui.freshness import render_freshness_banner

        render_freshness_banner()

    assert len(info_calls) == 1
    assert "6h ago" in info_calls[0]
