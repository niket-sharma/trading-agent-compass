"""Configuration loader: reads all YAML files and validates with Pydantic.

Settings load once per process and are treated as immutable. Call get_config()
anywhere — it caches the result on first load.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

_CONFIG_DIR = Path(__file__).parent.parent / "config"


# ──────────────────────────────────────────────
# Universe
# ──────────────────────────────────────────────


class UniverseConfig(BaseModel):
    etfs: list[str]
    single_names: list[str]
    benchmarks: list[str]
    ndx_symbol: str = "^NDX"
    vix_symbol: str = "^VIX"

    @property
    def all_tickers(self) -> list[str]:
        return self.etfs + self.single_names

    @property
    def all_symbols(self) -> list[str]:
        return self.etfs + self.single_names + self.benchmarks + [self.ndx_symbol, self.vix_symbol]


# ──────────────────────────────────────────────
# Risk profiles
# ──────────────────────────────────────────────


class AllocationWeights(BaseModel):
    base: float
    leveraged_2x: float
    leveraged_3x_long: float
    leveraged_3x_medium: float
    leveraged_3x_short: float
    cash: float

    @model_validator(mode="after")
    def weights_sum_to_one(self) -> AllocationWeights:
        total = (
            self.base
            + self.leveraged_2x
            + self.leveraged_3x_long
            + self.leveraged_3x_medium
            + self.leveraged_3x_short
            + self.cash
        )
        if abs(total - 1.0) > 0.001:
            raise ValueError(f"Bucket weights must sum to 1.0, got {total:.4f}")
        return self


class RecurringContribution(BaseModel):
    amount: float = 1000.0
    frequency: str = "monthly"

    @field_validator("frequency")
    @classmethod
    def valid_frequency(cls, v: str) -> str:
        allowed = {"daily", "weekly", "monthly", "quarterly", "never"}
        if v not in allowed:
            raise ValueError(f"frequency must be one of {allowed}, got {v!r}")
        return v


class ProfileConfig(BaseModel):
    name: str
    description: str = ""
    risk_level: int = Field(ge=1, le=10)
    aggression: int = Field(ge=1, le=10)
    max_leverage: float = Field(ge=1.0, le=3.0)
    volatility_tolerance: str
    trading_intensity: str
    st_tax_rate: float = Field(ge=0.0, le=1.0, default=0.32)
    lt_tax_rate: float = Field(ge=0.0, le=1.0, default=0.15)
    recurring_contribution: RecurringContribution = Field(
        default_factory=RecurringContribution
    )
    constraints: list[dict[str, Any]] = Field(default_factory=list)
    allocation_by_regime: dict[str, AllocationWeights]

    @field_validator("volatility_tolerance")
    @classmethod
    def valid_vt(cls, v: str) -> str:
        allowed = {"low", "medium", "high"}
        if v not in allowed:
            raise ValueError(f"volatility_tolerance must be one of {allowed}")
        return v

    @field_validator("trading_intensity")
    @classmethod
    def valid_ti(cls, v: str) -> str:
        allowed = {"passive", "moderate", "active"}
        if v not in allowed:
            raise ValueError(f"trading_intensity must be one of {allowed}")
        return v


# ──────────────────────────────────────────────
# Strategy params (simplified — full detail in YAML)
# ──────────────────────────────────────────────


class DeploymentConfig(BaseModel):
    github_owner: str
    github_repo: str
    refresh_workflow_filename: str


class BacktestConfig(BaseModel):
    default_start: str = "2015-01-01"
    default_end: str = "2024-12-31"
    initial_capital: float = 100_000.0
    commission_pct: float = 0.0
    slippage_bps: dict[str, float] = Field(default_factory=dict)
    recurring_contribution: RecurringContribution = Field(
        default_factory=RecurringContribution
    )


class StrategyParamsConfig(BaseModel):
    deployment: DeploymentConfig
    backtest: BacktestConfig = Field(default_factory=BacktestConfig)
    # Remaining keys kept as raw dicts for Phase 1+ to consume
    regime: dict[str, Any] = Field(default_factory=dict)
    buckets: dict[str, Any] = Field(default_factory=dict)
    signal_weights: dict[str, float] = Field(default_factory=dict)
    safety: dict[str, Any] = Field(default_factory=dict)


# ──────────────────────────────────────────────
# App config — aggregates everything
# ──────────────────────────────────────────────


class AppConfig(BaseModel):
    universe: UniverseConfig
    strategy: StrategyParamsConfig
    profiles: dict[str, ProfileConfig]


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open() as f:
        return yaml.safe_load(f)


def _load_app_config(config_dir: Path = _CONFIG_DIR) -> AppConfig:
    universe_data = _load_yaml(config_dir / "universe.yaml")
    strategy_data = _load_yaml(config_dir / "strategy_params.yaml")

    profiles: dict[str, ProfileConfig] = {}
    for pf_path in (config_dir / "profiles").glob("*.yaml"):
        raw = _load_yaml(pf_path)
        profiles[raw["name"]] = ProfileConfig(**raw)

    return AppConfig(
        universe=UniverseConfig(**universe_data),
        strategy=StrategyParamsConfig(**strategy_data),
        profiles=profiles,
    )


@functools.lru_cache(maxsize=1)
def get_config() -> AppConfig:
    """Load and validate all configuration YAML files. Cached after first call."""
    return _load_app_config()
