"""Tests for the secrets resolution helper."""

from __future__ import annotations

from unittest.mock import patch

import pytest


def test_get_secret_from_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TEST_SECRET_KEY", "env-value")
    # Patch streamlit so it's not importable (simulating non-Streamlit context)
    with patch.dict("sys.modules", {"streamlit": None}):
        from importlib import reload

        import tradeagent.secrets as sec_mod
        reload(sec_mod)

        val = sec_mod.get_secret("TEST_SECRET_KEY", allow_session=False)
        assert val == "env-value"


def test_get_secret_returns_none_when_missing(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("DEFINITELY_NOT_SET", raising=False)
    with patch.dict("sys.modules", {"streamlit": None}):
        from importlib import reload

        import tradeagent.secrets as sec_mod
        reload(sec_mod)

        val = sec_mod.get_secret("DEFINITELY_NOT_SET", allow_session=False)
        assert val is None


def test_require_secret_raises_when_missing(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("MISSING_KEY", raising=False)
    with patch.dict("sys.modules", {"streamlit": None}):
        from importlib import reload

        import tradeagent.secrets as sec_mod
        reload(sec_mod)

        with pytest.raises(EnvironmentError, match="MISSING_KEY"):
            sec_mod.require_secret("MISSING_KEY", allow_session=False)
