"""Per-bucket signal generation.

Given a regime, profile allocation targets, and current portfolio state,
produce BUY / SELL / HOLD signals for each bucket.

Pure: no I/O, no Streamlit. The caller passes in all necessary data.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class Signal:
    action: str               # "BUY" | "SELL" | "HOLD"
    ticker: str
    bucket: str               # bucket name (e.g. "base", "leveraged_2x")
    target_pct: float         # fraction of total portfolio to move (positive)
    limit_price: float | None # None → use market price
    urgency: str              # "high" | "medium" | "low"
    confidence: float         # 0.0-1.0
    reasoning: dict[str, str] = field(default_factory=dict)


BUCKET_TICKERS: dict[str, list[str]] = {
    "base": ["QQQ"],
    "leveraged_2x": ["QLD"],
    "leveraged_3x_long": ["TQQQ"],
    "leveraged_3x_medium": ["TQQQ"],
    "leveraged_3x_short": ["TQQQ", "SQQQ"],
    "cash": [],
}

# Short bucket: use SQQQ in bear/strong_bear, TQQQ otherwise
_BEAR_REGIMES = {"bear", "strong_bear"}


def generate_signals(
    regime: str,
    target_weights: dict[str, float],
    current_weights: dict[str, float],
    technical_scores: dict[str, float],
    prices: dict[str, float],
    *,
    rebalance_threshold: float = 0.05,
    portfolio_value: float = 100_000.0,
    as_of: date | None = None,
) -> list[Signal]:
    """Generate BUY/SELL/HOLD signals per bucket.

    Args:
        regime: Current regime string (e.g. "bull").
        target_weights: Target bucket weights from allocation.compute_target_weights().
        current_weights: Current bucket weights (current $ / total portfolio).
        technical_scores: {ticker: composite_score} from technical.compute_technical_score().
        prices: {ticker: latest_close} for limit-price hints.
        rebalance_threshold: Minimum weight delta that triggers a trade (avoids micro-trades).
        portfolio_value: Total portfolio value in $.
        as_of: Date for the signal (informational only).

    Returns:
        List of Signal objects. May be empty if no rebalancing needed.
    """
    signals: list[Signal] = []

    for bucket, target in target_weights.items():
        if bucket == "cash":
            continue
        current = current_weights.get(bucket, 0.0)
        delta = target - current

        if abs(delta) < rebalance_threshold:
            continue

        tickers = BUCKET_TICKERS.get(bucket, [])
        if not tickers:
            continue

        # Pick the right ticker for the short bucket
        if bucket == "leveraged_3x_short":
            ticker = "SQQQ" if regime in _BEAR_REGIMES else "TQQQ"
        else:
            ticker = tickers[0]

        limit_price = prices.get(ticker)
        tech = technical_scores.get(ticker, 0.0)

        # Confidence = blend of regime conviction and technical alignment
        if delta > 0:
            action = "BUY"
            # Bullish technical score increases confidence for buys
            confidence = min(1.0, 0.6 + 0.4 * max(0.0, tech))
        else:
            action = "SELL"
            # Bearish technical score increases confidence for sells
            confidence = min(1.0, 0.6 + 0.4 * max(0.0, -tech))

        urgency = "high" if abs(delta) > 0.15 else ("medium" if abs(delta) > 0.08 else "low")

        signals.append(
            Signal(
                action=action,
                ticker=ticker,
                bucket=bucket,
                target_pct=abs(delta),
                limit_price=limit_price,
                urgency=urgency,
                confidence=round(confidence, 3),
                reasoning={
                    "regime": regime,
                    "target_weight": f"{target:.1%}",
                    "current_weight": f"{current:.1%}",
                    "delta": f"{delta:+.1%}",
                    "tech_score": f"{tech:+.3f}",
                },
            )
        )

    # Sort: sells first (free up cash), then buys by urgency
    sells = sorted([s for s in signals if s.action == "SELL"], key=lambda s: -s.target_pct)
    buys = sorted(
        [s for s in signals if s.action == "BUY"],
        key=lambda s: (-{"high": 3, "medium": 2, "low": 1}[s.urgency], -s.confidence),
    )
    return sells + buys
