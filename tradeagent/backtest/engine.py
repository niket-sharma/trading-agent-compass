"""Walk-forward backtest engine.

Design principles:
    - No lookahead bias: at each step T, only data with index <= T is visible.
    - In-memory only: no disk writes at any point.
    - Deterministic: same inputs → same outputs.
    - Tax-lot aware: FIFO / HIFO lot selection with ST vs LT tracking.

Usage:
    result = run_backtest(prices, regime_fn, signal_fn, config)
    # result.equity_curve, result.trades, result.metrics
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from tradeagent.backtest.metrics import compute_all

# ── Data structures ───────────────────────────────────────────────────────────


@dataclass
class Lot:
    """A single tax lot."""
    ticker: str
    shares: float
    cost_basis: float   # per share
    purchase_date: date
    lot_id: str


@dataclass
class Trade:
    """A completed or partial trade."""
    date: date
    ticker: str
    action: str          # "BUY" | "SELL"
    shares: float
    price: float
    gross_proceeds: float
    realized_pnl: float
    is_long_term: bool   # holding > 365 days
    lot_id: str
    reasoning: str = ""


@dataclass
class BacktestResult:
    """Output of run_backtest."""
    equity_curve: pd.Series          # Date-indexed portfolio value
    trades: list[Trade]
    metrics: dict[str, float]        # CAGR, drawdown, Sharpe, …
    benchmark_equity: pd.Series      # QQQ buy-and-hold baseline
    regime_series: pd.Series         # Date-indexed regime strings
    decision_log: list[dict]         # Full daily reasoning trace
    tax_summary: dict[str, float]    # st_gains, lt_gains, total_tax_drag


@dataclass
class BacktestConfig:
    start: date
    end: date
    initial_capital: float = 100_000.0
    commission_pct: float = 0.0
    slippage_bps: dict[str, float] = field(default_factory=lambda: {"default": 2})
    benchmark_ticker: str = "QQQ"


# ── Tax-lot helpers ───────────────────────────────────────────────────────────


def _is_long_term(purchase_date: date, sell_date: date) -> bool:
    return (sell_date - purchase_date).days > 365


def _hifo_lots(lots: list[Lot]) -> list[Lot]:
    """Highest-cost-basis-first ordering (minimizes realized gains)."""
    return sorted(lots, key=lambda x: -x.cost_basis)


def _sell_lots(
    lots: list[Lot],
    shares_to_sell: float,
    sell_date: date,
    sell_price: float,
    ordering: str = "hifo",
) -> tuple[list[Trade], list[Lot], float]:
    """
    Sell `shares_to_sell` from `lots` using the given ordering.

    Returns:
        (trades_executed, remaining_lots, total_realized_pnl)
    """
    ordered = _hifo_lots(lots) if ordering == "hifo" else sorted(lots, key=lambda x: x.purchase_date)

    trades: list[Trade] = []
    remaining: list[Lot] = []
    still_to_sell = shares_to_sell

    for lot in ordered:
        if still_to_sell <= 1e-6:
            remaining.append(lot)
            continue
        sold = min(lot.shares, still_to_sell)
        still_to_sell -= sold
        pnl = (sell_price - lot.cost_basis) * sold
        lt = _is_long_term(lot.purchase_date, sell_date)
        trades.append(
            Trade(
                date=sell_date,
                ticker=lot.ticker,
                action="SELL",
                shares=sold,
                price=sell_price,
                gross_proceeds=sold * sell_price,
                realized_pnl=pnl,
                is_long_term=lt,
                lot_id=lot.lot_id,
            )
        )
        if lot.shares - sold > 1e-6:
            remaining.append(
                Lot(
                    ticker=lot.ticker,
                    shares=lot.shares - sold,
                    cost_basis=lot.cost_basis,
                    purchase_date=lot.purchase_date,
                    lot_id=lot.lot_id,
                )
            )

    return trades, remaining, sum(t.realized_pnl for t in trades)


# ── Slippage ──────────────────────────────────────────────────────────────────


def _apply_slippage(price: float, ticker: str, action: str, slippage_bps: dict[str, float]) -> float:
    bps = slippage_bps.get(ticker, slippage_bps.get("default", 2))
    factor = bps / 10_000
    return price * (1 + factor) if action == "BUY" else price * (1 - factor)


# ── Main engine ───────────────────────────────────────────────────────────────


def run_backtest(
    prices: dict[str, pd.DataFrame],
    regime_fn: Callable[[pd.DataFrame, date], str],
    signal_fn: Callable[[str, pd.DataFrame, str, float], list[dict]],
    config: BacktestConfig,
    macro: dict[str, pd.DataFrame] | None = None,
    vix_prices: pd.DataFrame | None = None,
    breadth_prices: dict[str, pd.DataFrame] | None = None,
) -> BacktestResult:
    """Walk-forward backtest.

    Args:
        prices: Dict {ticker: price_df} with columns [date, close, ...].
                Must cover config.start to config.end.
        regime_fn: Pure function (ndx_df_to_date_T, date_T) -> regime_str.
                   Called each day with data truncated to that day.
        signal_fn: Pure function (regime, ndx_df, portfolio_value, date) -> list of signal dicts.
                   Each signal dict: {ticker, action, target_pct, reasoning}.
        config: BacktestConfig.
        macro, vix_prices, breadth_prices: Optional data passed to regime_fn.

    Returns:
        BacktestResult.
    """
    # Build trading day calendar from the benchmark prices
    bench_ticker = config.benchmark_ticker
    bench_df = prices.get(bench_ticker, pd.DataFrame())
    if bench_df.empty:
        raise ValueError(f"Benchmark ticker {bench_ticker!r} not found in prices dict.")

    bench_df = bench_df.copy()
    bench_df["date"] = pd.to_datetime(bench_df["date"]).dt.date
    trading_days = sorted(
        d for d in bench_df["date"] if config.start <= d <= config.end
    )

    if not trading_days:
        raise ValueError(f"No trading days between {config.start} and {config.end}.")

    # Portfolio state
    cash = config.initial_capital
    lots: dict[str, list[Lot]] = {}      # ticker → list of Lot
    lot_counter = 0
    all_trades: list[Trade] = []
    decision_log: list[dict] = []
    equity_series: dict[date, float] = {}
    regime_series: dict[date, str] = {}
    st_gains = lt_gains = 0.0

    def _portfolio_value(as_of: date) -> float:
        total = cash
        for ticker, ticker_lots in lots.items():
            price = _get_price(prices[ticker], as_of) if ticker in prices else 0.0
            total += sum(lot.shares * price for lot in ticker_lots)
        return total

    def _get_price(df: pd.DataFrame, d: date) -> float:
        df2 = df.copy()
        df2["date"] = pd.to_datetime(df2["date"]).dt.date
        row = df2[df2["date"] == d]
        if row.empty:
            # Use most recent prior price
            prior = df2[df2["date"] <= d]
            return float(prior["close"].iloc[-1]) if not prior.empty else 0.0
        return float(row["close"].iloc[0])

    def _truncate_to(df: pd.DataFrame, d: date) -> pd.DataFrame:
        df2 = df.copy()
        df2["date"] = pd.to_datetime(df2["date"]).dt.date
        return df2[df2["date"] <= d].copy()

    for day in trading_days:
        # Regime classification (no lookahead: only data <= day)
        ndx_trunc = _truncate_to(prices.get(bench_ticker, pd.DataFrame()), day)
        vix_trunc = _truncate_to(vix_prices, day) if vix_prices is not None else pd.DataFrame()
        breadth_trunc = (
            {t: _truncate_to(df, day) for t, df in breadth_prices.items()}
            if breadth_prices else {}
        )
        macro_trunc = (
            {k: _truncate_to(df, day) for k, df in macro.items()}
            if macro else {}
        )
        regime = regime_fn(ndx_trunc, vix_trunc, macro_trunc, breadth_trunc, day)
        regime_series[day] = regime

        portfolio_val = _portfolio_value(day)

        # Get signals
        signals = signal_fn(regime, ndx_trunc, portfolio_val, day)

        # Execute signals
        for sig in signals:
            ticker = sig.get("ticker", bench_ticker)
            action = sig.get("action", "HOLD")
            target_pct = float(sig.get("target_pct", 0.0))
            reasoning = sig.get("reasoning", "")

            if action == "HOLD" or ticker not in prices:
                continue

            price = _get_price(prices[ticker], day)
            if price <= 0:
                continue
            exec_price = _apply_slippage(price, ticker, action, config.slippage_bps)
            commission = exec_price * abs(target_pct) * portfolio_val / exec_price * config.commission_pct

            if action == "BUY":
                target_value = target_pct * portfolio_val
                affordable = min(target_value, cash - commission)
                if affordable <= 0:
                    continue
                shares = affordable / exec_price
                cash -= shares * exec_price + commission
                lot = Lot(
                    ticker=ticker,
                    shares=shares,
                    cost_basis=exec_price,
                    purchase_date=day,
                    lot_id=f"{ticker}-{lot_counter}",
                )
                lot_counter += 1
                lots.setdefault(ticker, []).append(lot)
                all_trades.append(
                    Trade(
                        date=day,
                        ticker=ticker,
                        action="BUY",
                        shares=shares,
                        price=exec_price,
                        gross_proceeds=shares * exec_price,
                        realized_pnl=0.0,
                        is_long_term=False,
                        lot_id=lot.lot_id,
                        reasoning=reasoning,
                    )
                )

            elif action == "SELL":
                ticker_lots = lots.get(ticker, [])
                if not ticker_lots:
                    continue
                current_value = sum(lot.shares * exec_price for lot in ticker_lots)
                sell_value = min(abs(target_pct) * portfolio_val, current_value)
                shares_to_sell = sell_value / exec_price
                executed, remaining, _pnl = _sell_lots(ticker_lots, shares_to_sell, day, exec_price)
                lots[ticker] = remaining
                cash += sell_value - commission
                for t in executed:
                    t.reasoning = reasoning
                    if t.is_long_term:
                        lt_gains += t.realized_pnl
                    else:
                        st_gains += t.realized_pnl
                all_trades.extend(executed)

        equity_series[day] = _portfolio_value(day)
        decision_log.append(
            {
                "date": day,
                "regime": regime,
                "portfolio_value": equity_series[day],
                "signals": signals,
            }
        )

    equity = pd.Series(equity_series)
    equity.index = pd.to_datetime(equity.index)

    # Build benchmark equity (buy-and-hold from day 1)
    bench_prices = bench_df.set_index("date")["close"].reindex(list(trading_days))
    bench_equity = config.initial_capital * bench_prices / bench_prices.iloc[0]
    bench_equity.index = pd.to_datetime(bench_equity.index)

    return BacktestResult(
        equity_curve=equity,
        trades=all_trades,
        metrics=compute_all(equity),
        benchmark_equity=bench_equity,
        regime_series=pd.Series(regime_series),
        decision_log=decision_log,
        tax_summary={
            "st_gains": round(st_gains, 2),
            "lt_gains": round(lt_gains, 2),
        },
    )


# ── Convenience: buy-and-hold backtest ───────────────────────────────────────


def buy_and_hold_backtest(
    prices: dict[str, pd.DataFrame],
    ticker: str,
    config: BacktestConfig,
) -> BacktestResult:
    """Simple buy-and-hold for a single ticker. Used for benchmark comparison."""

    def _regime_fn(*_args, **_kwargs) -> str:
        return "neutral"

    invested = False

    def _signal_fn(regime: str, ndx: pd.DataFrame, portfolio_val: float, d: date) -> list[dict]:
        nonlocal invested
        if not invested:
            invested = True
            return [{"ticker": ticker, "action": "BUY", "target_pct": 1.0, "reasoning": "initial buy"}]
        return []

    return run_backtest(
        prices={ticker: prices[ticker]},
        regime_fn=_regime_fn,
        signal_fn=_signal_fn,
        config=config,
    )
