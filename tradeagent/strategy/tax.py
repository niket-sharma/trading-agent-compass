"""Tax-aware lot selection for sell decisions.

HIFO (Highest-cost-basis-first) by default to minimize realized gains.
Switches to tax-loss harvesting when a lot has an unrealized loss.
Wash-sale advisory: flags if a re-buy within 30 days would trigger a wash sale.

Pure: no I/O, no Streamlit.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass
class LotInfo:
    lot_id: str
    ticker: str
    shares: float
    cost_basis: float   # per share
    purchase_date: date
    current_price: float

    @property
    def unrealized_pnl(self) -> float:
        return (self.current_price - self.cost_basis) * self.shares

    @property
    def is_long_term(self) -> bool:
        from datetime import date as date_cls
        return (date_cls.today() - self.purchase_date).days > 365

    @property
    def tax_label(self) -> str:
        return "LT" if self.is_long_term else "ST"


def select_lots_to_sell(
    lots: list[LotInfo],
    shares_needed: float,
    *,
    strategy: str = "hifo",
    prefer_losses: bool = True,
) -> tuple[list[LotInfo], bool]:
    """Select which lots to use for a sell.

    Args:
        lots: Available lots for this ticker.
        shares_needed: Total shares to sell.
        strategy: "hifo" (minimize gains) or "fifo" (first in, first out).
        prefer_losses: If True and any lots have unrealized losses, sell them first
                       (tax-loss harvesting). Overrides the ordering strategy.

    Returns:
        (selected_lots, wash_sale_risk)
        - selected_lots: Lots to sell (may need partial sell on the last lot).
        - wash_sale_risk: True if all selected lots have losses (buyer should wait 31 days
          before re-buying the same ticker to avoid wash-sale rule).
    """
    if not lots:
        return [], False

    # Tax-loss harvesting pass: prefer lots with unrealized losses
    if prefer_losses:
        loss_lots = [lot for lot in lots if lot.unrealized_pnl < 0]
        if loss_lots:
            ordered = sorted(loss_lots, key=lambda x: x.unrealized_pnl)  # biggest losses first
            ordered += [lot for lot in lots if lot not in loss_lots]
        else:
            ordered = _order_lots(lots, strategy)
    else:
        ordered = _order_lots(lots, strategy)

    selected: list[LotInfo] = []
    remaining = shares_needed
    for lot in ordered:
        if remaining <= 1e-6:
            break
        selected.append(lot)
        remaining -= lot.shares

    wash_sale_risk = all(lot.unrealized_pnl < 0 for lot in selected) if selected else False
    return selected, wash_sale_risk


def _order_lots(lots: list[LotInfo], strategy: str) -> list[LotInfo]:
    if strategy == "hifo":
        return sorted(lots, key=lambda x: -x.cost_basis)
    return sorted(lots, key=lambda x: x.purchase_date)  # fifo


def wash_sale_days_remaining(last_sale_date: date, today: date | None = None) -> int:
    """Days until wash-sale window expires (30 days after sale)."""
    today = today or date.today()
    window_end = last_sale_date + timedelta(days=31)
    return max(0, (window_end - today).days)


def format_lot_summary(lot: LotInfo) -> str:
    """Human-readable lot description for the UI."""
    gain = lot.unrealized_pnl
    return (
        f"{lot.ticker} {lot.shares:.2f} sh @ ${lot.cost_basis:.2f} "
        f"({lot.tax_label}, bought {lot.purchase_date:%Y-%m-%d}, "
        f"unrealized {'+' if gain>=0 else ''}{gain:,.0f})"
    )
