"""tradectl — CLI for pre-fetching and managing static data.

Dev-only: used locally and by GitHub Actions. Not imported by the Streamlit app.

Usage examples:
  tradectl config validate
  tradectl refresh prices --universe --since 2010-01-01
  tradectl refresh news --universe --days 7
  tradectl refresh all --since 2010-01-01
  tradectl status
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from tradeagent.logging_config import configure_logging

configure_logging()

import structlog  # noqa: E402

log = structlog.get_logger(__name__)

app = typer.Typer(help="Trading Agent CLI — manage static data and config.")
refresh_app = typer.Typer(help="Refresh static data.")
app.add_typer(refresh_app, name="refresh")

console = Console()

_DEFAULT_SINCE = date(2010, 1, 1)


def _load_universe() -> list[str]:
    from tradeagent.config import get_config

    cfg = get_config()
    return cfg.universe.all_tickers


# ──────────────────────────────────────────────
# config
# ──────────────────────────────────────────────


@app.command()
def config_validate() -> None:
    """Validate all config YAML files and print a summary."""
    from tradeagent.config import get_config

    try:
        cfg = get_config()
        console.print("[green]✓ Config valid[/green]")
        console.print(f"  Universe: {cfg.universe.all_tickers}")
        console.print(f"  Profiles: {list(cfg.profiles.keys())}")
        console.print(f"  Deployment: {cfg.strategy.deployment.github_repo}")
    except Exception as exc:
        console.print(f"[red]✗ Config invalid:[/red] {exc}")
        raise typer.Exit(1) from exc


# Override the CLI command name to avoid "config-validate" vs "config validate"
app.command(name="config")(config_validate)


# ──────────────────────────────────────────────
# refresh prices
# ──────────────────────────────────────────────


@refresh_app.command(name="prices")
def refresh_prices(
    ticker: str | None = typer.Option(None, "--ticker", "-t", help="Single ticker"),
    universe: bool = typer.Option(False, "--universe", "-u", help="All universe tickers"),
    since: date = typer.Option(_DEFAULT_SINCE, "--since", help="Fetch bars since this date"),  # noqa: B008
) -> None:
    """Fetch daily price bars from yfinance and save to data/prices/."""
    from tradeagent.data.prices import fetch_daily_bars, fetch_dividends, fetch_splits
    from tradeagent.data.store import save_corporate_actions, save_prices

    tickers = _resolve_tickers(ticker, universe)
    for t in tickers:
        console.print(f"[cyan]prices[/cyan] {t} since {since}...")
        df = fetch_daily_bars(t, since)
        if not df.empty:
            save_prices(t, df)
            console.print(f"  saved {len(df)} rows, last date {df['date'].max().date()}")
        else:
            console.print("  [yellow]no data returned[/yellow]")

        # Corporate actions
        divs = fetch_dividends(t)
        splits = fetch_splits(t)
        import pandas as pd

        actions = pd.concat([divs, splits], ignore_index=True)
        if not actions.empty:
            save_corporate_actions(t, actions)


# ──────────────────────────────────────────────
# refresh fundamentals
# ──────────────────────────────────────────────


@refresh_app.command(name="fundamentals")
def refresh_fundamentals(
    ticker: str | None = typer.Option(None, "--ticker", "-t"),
    universe: bool = typer.Option(False, "--universe", "-u"),
) -> None:
    """Fetch quarterly and annual fundamentals from yfinance."""
    import pandas as pd

    from tradeagent.data.fundamentals import fetch_annual, fetch_quarterly
    from tradeagent.data.store import save_fundamentals

    tickers = _resolve_tickers(ticker, universe)
    for t in tickers:
        console.print(f"[cyan]fundamentals[/cyan] {t}...")
        q = fetch_quarterly(t)
        a = fetch_annual(t)
        combined = pd.concat([q, a], ignore_index=True)
        if not combined.empty:
            save_fundamentals(t, combined)
            console.print(f"  saved {len(combined)} rows")


# ──────────────────────────────────────────────
# refresh news
# ──────────────────────────────────────────────


@refresh_app.command(name="news")
def refresh_news(
    ticker: str | None = typer.Option(None, "--ticker", "-t"),
    universe: bool = typer.Option(False, "--universe", "-u"),
    days: int = typer.Option(7, "--days", "-d", help="Fetch last N days of articles"),
) -> None:
    """Fetch news articles from Tiingo and upsert into data/news/."""
    from tradeagent.data.news import fetch_articles
    from tradeagent.data.store import save_news

    tickers = _resolve_tickers(ticker, universe)
    for t in tickers:
        console.print(f"[cyan]news[/cyan] {t} last {days} days...")
        df = fetch_articles(t, days)
        save_news(t, df)
        console.print(f"  upserted {len(df)} articles")


# ──────────────────────────────────────────────
# refresh macro
# ──────────────────────────────────────────────


@refresh_app.command(name="macro")
def refresh_macro(
    since: date = typer.Option(_DEFAULT_SINCE, "--since"),  # noqa: B008
) -> None:
    """Fetch macro series from FRED and VIX from yfinance."""
    from tradeagent.data.macro import fetch_common_macro
    from tradeagent.data.store import save_macro

    console.print("[cyan]macro[/cyan] fetching common macro series...")
    series = fetch_common_macro(since)
    for series_id, df in series.items():
        if not df.empty:
            save_macro(series_id, df)
            console.print(f"  {series_id}: {len(df)} rows")
        else:
            console.print(f"  {series_id}: [yellow]no data[/yellow]")


# ──────────────────────────────────────────────
# refresh all
# ──────────────────────────────────────────────


@refresh_app.command(name="all")
def refresh_all(
    since: date = typer.Option(_DEFAULT_SINCE, "--since"),  # noqa: B008
    news_days: int = typer.Option(7, "--news-days"),
) -> None:
    """Refresh prices, fundamentals, macro, and news for the full universe."""
    from tradeagent.config import get_config

    get_config()  # validate config eagerly

    console.rule("[bold]Refresh: prices[/bold]")
    refresh_prices(ticker=None, universe=True, since=since)

    console.rule("[bold]Refresh: fundamentals[/bold]")
    refresh_fundamentals(ticker=None, universe=True)

    console.rule("[bold]Refresh: macro[/bold]")
    refresh_macro(since=since)

    console.rule("[bold]Refresh: news[/bold]")
    refresh_news(ticker=None, universe=True, days=news_days)

    console.rule("[bold]Done[/bold]")


# ──────────────────────────────────────────────
# status
# ──────────────────────────────────────────────


@app.command()
def status() -> None:
    """Show row counts, last dates, and disk usage for each data file."""
    from tradeagent.data.macro import COMMON_SERIES
    from tradeagent.data.store import get_last_date, list_available_tickers, load_macro

    table = Table(title="Data Status")
    table.add_column("Type")
    table.add_column("Key")
    table.add_column("Rows")
    table.add_column("Last Date")
    table.add_column("File Size")

    data_dir = Path("data")

    # Prices
    for ticker in list_available_tickers():
        path = data_dir / "prices" / f"{ticker}.parquet"
        d = get_last_date(ticker)
        size = f"{path.stat().st_size // 1024} KB" if path.exists() else "—"
        import pandas as pd

        df = pd.read_parquet(path) if path.exists() else pd.DataFrame()
        table.add_row("prices", ticker, str(len(df)), str(d) if d else "—", size)

    # Macro
    for series_id in [*list(COMMON_SERIES.keys()), "VIX"]:
        path = data_dir / "macro" / f"{series_id}.parquet"
        if path.exists():
            df = load_macro(series_id)
            size = f"{path.stat().st_size // 1024} KB"
            last = str(df["date"].max().date()) if not df.empty else "—"
            table.add_row("macro", series_id, str(len(df)), last, size)

    console.print(table)


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────


def _resolve_tickers(ticker: str | None, universe: bool) -> list[str]:
    if ticker:
        return [ticker.upper()]
    if universe:
        return _load_universe()
    console.print("[red]Error:[/red] Provide --ticker or --universe")
    raise typer.Exit(1)


if __name__ == "__main__":
    app()
