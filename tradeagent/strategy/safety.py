"""Safety overlays: throttle signal sizes under adverse conditions.

All functions are pure — they take signals and return scaled signals.
No I/O, no Streamlit.
"""
from __future__ import annotations

from tradeagent.strategy.signals import Signal


def apply_safety_overlays(
    signals: list[Signal],
    *,
    vix_level: float = 0.0,
    consecutive_losses: int = 0,
    regime_score: float = 0.0,
    vix_throttle_threshold: float = 30.0,
    consecutive_loss_throttle: int = 3,
    confidence_throttle_zone: float = 0.10,
) -> list[Signal]:
    """Scale down signal target_pcts under adverse conditions.

    All throttles multiply target_pct — they never change direction or zero out signals.

    Args:
        signals: Output of generate_signals().
        vix_level: Current VIX level.
        consecutive_losses: Number of consecutive losing trades.
        regime_score: Composite regime score in [-1, 1]. Near-boundary → reduce size.
        vix_throttle_threshold: Above this VIX level, leverage buckets are throttled.
        consecutive_loss_throttle: After this many consecutive losses, halve size.
        confidence_throttle_zone: If |score - boundary| < this, reduce by 30%.

    Returns:
        New list of Signal objects with adjusted target_pcts.
    """
    LEVERAGED_BUCKETS = {"leveraged_2x", "leveraged_3x_long", "leveraged_3x_medium", "leveraged_3x_short"}

    throttled = []
    for sig in signals:
        multiplier = 1.0

        # VIX throttle: high vol → reduce leveraged bucket sizes
        if sig.bucket in LEVERAGED_BUCKETS and vix_level > vix_throttle_threshold:
            excess = (vix_level - vix_throttle_threshold) / 10.0  # 0 at threshold, 1 at +10 pts
            multiplier *= max(0.3, 1.0 - excess * 0.5)

        # Consecutive loss throttle
        if consecutive_losses >= consecutive_loss_throttle:
            multiplier *= 0.5

        # Regime confidence throttle: score near regime boundary → hesitate
        BOUNDARIES = [0.60, 0.20, -0.20, -0.60]
        near_boundary = any(abs(regime_score - b) < confidence_throttle_zone for b in BOUNDARIES)
        if near_boundary:
            multiplier *= 0.70

        new_sig = Signal(
            action=sig.action,
            ticker=sig.ticker,
            bucket=sig.bucket,
            target_pct=round(sig.target_pct * multiplier, 4),
            limit_price=sig.limit_price,
            urgency=sig.urgency,
            confidence=sig.confidence,
            reasoning={**sig.reasoning, "safety_multiplier": f"{multiplier:.2f}"},
        )
        throttled.append(new_sig)

    return throttled
