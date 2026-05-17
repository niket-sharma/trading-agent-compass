"""Tests for config loading and validation."""

from __future__ import annotations

from pathlib import Path

import pytest


def _reset_config_cache() -> None:
    """Clear the lru_cache on get_config so we get a fresh load each test."""
    from tradeagent import config as cfg_mod

    cfg_mod.get_config.cache_clear()


def test_get_config_loads_successfully() -> None:
    _reset_config_cache()
    from tradeagent.config import get_config

    cfg = get_config()
    assert cfg.universe.etfs == ["QQQ", "QLD", "TQQQ", "SQQQ"]
    assert "MSFT" in cfg.universe.single_names
    assert "moderate" in cfg.profiles
    assert cfg.strategy.deployment.github_repo == "trading-agent-compass"


def test_universe_all_tickers() -> None:
    _reset_config_cache()
    from tradeagent.config import get_config

    cfg = get_config()
    all_t = cfg.universe.all_tickers
    assert "QQQ" in all_t
    assert "MSFT" in all_t
    assert "SPY" not in all_t  # benchmarks excluded from all_tickers


def test_profiles_allocation_sum_to_one() -> None:
    _reset_config_cache()
    from tradeagent.config import get_config

    cfg = get_config()
    for name, profile in cfg.profiles.items():
        for regime, weights in profile.allocation_by_regime.items():
            total = (
                weights.base
                + weights.leveraged_2x
                + weights.leveraged_3x_long
                + weights.leveraged_3x_medium
                + weights.leveraged_3x_short
                + weights.cash
            )
            assert abs(total - 1.0) < 0.001, (
                f"Profile {name} regime {regime} weights sum to {total:.4f}"
            )


def test_all_three_profiles_present() -> None:
    _reset_config_cache()
    from tradeagent.config import get_config

    cfg = get_config()
    assert set(cfg.profiles.keys()) == {"conservative", "moderate", "aggressive"}


def test_invalid_profile_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A profile with weights that don't sum to 1.0 should raise at load time."""
    import yaml

    _reset_config_cache()

    # Copy real config dir structure, override one profile
    import shutil
    from pathlib import Path

    real_config = Path("config")
    dest = tmp_path / "config"
    shutil.copytree(real_config, dest)

    bad_profile = {
        "name": "bad",
        "description": "invalid",
        "risk_level": 5,
        "aggression": 5,
        "max_leverage": 1.5,
        "volatility_tolerance": "medium",
        "trading_intensity": "moderate",
        "allocation_by_regime": {
            "strong_bull": {
                "base": 0.50,
                "leveraged_2x": 0.50,
                "leveraged_3x_long": 0.50,  # total > 1
                "leveraged_3x_medium": 0.00,
                "leveraged_3x_short": 0.00,
                "cash": 0.00,
            },
            "bull": {"base": 1.0, "leveraged_2x": 0, "leveraged_3x_long": 0,
                     "leveraged_3x_medium": 0, "leveraged_3x_short": 0, "cash": 0},
            "neutral": {"base": 1.0, "leveraged_2x": 0, "leveraged_3x_long": 0,
                        "leveraged_3x_medium": 0, "leveraged_3x_short": 0, "cash": 0},
            "bear": {"base": 1.0, "leveraged_2x": 0, "leveraged_3x_long": 0,
                     "leveraged_3x_medium": 0, "leveraged_3x_short": 0, "cash": 0},
            "strong_bear": {"base": 1.0, "leveraged_2x": 0, "leveraged_3x_long": 0,
                            "leveraged_3x_medium": 0, "leveraged_3x_short": 0, "cash": 0},
        },
    }
    (dest / "profiles" / "bad.yaml").write_text(yaml.dump(bad_profile))

    from tradeagent import config as cfg_mod

    monkeypatch.setattr(cfg_mod, "_CONFIG_DIR", dest)
    cfg_mod.get_config.cache_clear()

    with pytest.raises((ValueError, Exception)):
        cfg_mod._load_app_config(dest)

    cfg_mod.get_config.cache_clear()
