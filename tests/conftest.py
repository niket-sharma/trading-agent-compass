"""Shared pytest fixtures."""

from __future__ import annotations

import tempfile
from collections.abc import Generator
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest


@pytest.fixture()
def tmp_data_dir(monkeypatch: pytest.MonkeyPatch) -> Generator[Path, None, None]:
    """Create a temporary data/ directory and patch store._DATA_DIR to point to it."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        (tmp / "prices").mkdir()
        (tmp / "fundamentals").mkdir()
        (tmp / "macro").mkdir()
        (tmp / "corporate_actions").mkdir()
        (tmp / "news").mkdir()

        import tradeagent.data.store as store_mod

        monkeypatch.setattr(store_mod, "_DATA_DIR", tmp)
        yield tmp


@pytest.fixture()
def sample_price_df() -> pd.DataFrame:
    """A minimal price DataFrame for 5 trading days."""
    today = date.today()
    dates = [today - timedelta(days=i) for i in range(4, -1, -1)]
    return pd.DataFrame(
        {
            "date": pd.to_datetime(dates, utc=True),
            "open": [100.0 + i for i in range(5)],
            "high": [105.0 + i for i in range(5)],
            "low": [98.0 + i for i in range(5)],
            "close": [102.0 + i for i in range(5)],
            "adj_close": [102.0 + i for i in range(5)],
            "volume": [1_000_000 + i * 10_000 for i in range(5)],
        }
    )


@pytest.fixture()
def sample_news_df() -> pd.DataFrame:
    """A minimal news DataFrame."""
    import hashlib

    rows = []
    for i in range(5):
        url = f"https://example.com/article/{i}"
        rows.append(
            {
                "id": str(i),
                "ticker": "QQQ",
                "published_at": pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=i),
                "title": f"Article {i}",
                "url": url,
                "source": "example",
                "body": f"Body of article {i}",
                "hash": hashlib.sha256(url.encode()).hexdigest(),
            }
        )
    return pd.DataFrame(rows)
