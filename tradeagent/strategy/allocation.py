"""Allocation engine: given regime + profile, compute target bucket weights.

Pure function: (regime, profile, drawdown) -> target weights dict.
No I/O, no Streamlit calls.
"""
from __future__ import annotations

from tradeagent.analysis.regime import Regime
from tradeagent.config import ProfileConfig


def compute_target_weights(
    regime: Regime | str,
    profile: ProfileConfig,
    current_drawdown: float = 0.0,
    ema_alpha: float = 0.2,
    prev_weights: dict[str, float] | None = None,
) -> dict[str, float]:
    """Compute target bucket weights for a given regime and risk profile.

    Reads static allocations from profile.allocation_by_regime, then applies
    EMA smoothing toward the new target to avoid whipsaw over-trading.

    Args:
        regime: Current Regime enum or string value.
        profile: User's risk profile (loaded from profiles/*.yaml).
        current_drawdown: Current portfolio drawdown as a negative fraction
                          (e.g. -0.15). Large drawdowns throttle leverage.
        ema_alpha: EMA blending factor: 0.2 means 20% new target, 80% old.
                   Use 1.0 to skip smoothing (e.g. for backtesting clean transitions).
        prev_weights: Previous target weights (used for EMA smoothing).
                      None → use the raw profile weights directly.

    Returns:
        Dict of bucket → weight, always summing to 1.0.
        Buckets: base, leveraged_2x, leveraged_3x_long, leveraged_3x_medium,
                 leveraged_3x_short, cash.
    """
    regime_str = regime.value if isinstance(regime, Regime) else regime

    raw = profile.allocation_by_regime.get(regime_str)
    if raw is None:
        # Fallback: most conservative allocation
        raw = profile.allocation_by_regime.get("strong_bear") or next(
            iter(profile.allocation_by_regime.values())
        )

    target = {
        "base": raw.base,
        "leveraged_2x": raw.leveraged_2x,
        "leveraged_3x_long": raw.leveraged_3x_long,
        "leveraged_3x_medium": raw.leveraged_3x_medium,
        "leveraged_3x_short": raw.leveraged_3x_short,
        "cash": raw.cash,
    }

    # Drawdown throttle: reduce leveraged buckets proportionally when drawdown > 15%
    if current_drawdown < -0.15:
        severity = min(1.0, abs(current_drawdown + 0.15) / 0.20)  # 0 at -15%, 1 at -35%
        for bucket in ("leveraged_2x", "leveraged_3x_long", "leveraged_3x_medium", "leveraged_3x_short"):
            reduction = target[bucket] * severity * 0.50
            target[bucket] -= reduction
            target["cash"] += reduction

    # EMA smoothing
    if prev_weights is not None and ema_alpha < 1.0:
        smoothed = {}
        for k in target:
            smoothed[k] = ema_alpha * target[k] + (1.0 - ema_alpha) * prev_weights.get(k, target[k])
        # Re-normalise to sum=1 after blending
        total = sum(smoothed.values())
        if total > 0:
            target = {k: v / total for k, v in smoothed.items()}

    return target
