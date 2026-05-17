# PHASE_0_PROMPT.md — Foundations and First Deploy

> Paste this into Claude Code at the start of Phase 0. Claude Code should read `CLAUDE.md` and `PLAN.md` first, then this file.

## Your task

Build the Phase 0 foundations of the `trading-agent-compass` project per `PLAN.md § Phase 0`. The goal is a **minimal Streamlit app deployed to Streamlit Community Cloud from a private GitHub repo**, loading static price data from the repo and showing a chart. No analysis logic yet — but the deploy loop must work end-to-end.

This is a personal project for the owner's WSL2 machine + Streamlit Community Cloud. No Docker. No Postgres. No FastAPI. No Next.js.

## Order of work

Work in this exact order. After each step, commit and confirm before moving to the next.

### Step 1 — Repo scaffold and tooling

1. Create the directory structure from `CLAUDE.md § Repository layout`. Add `__init__.py` to every Python package.
2. `pyproject.toml` with the locked stack from `PLAN.md § Phase 0 deliverable 2`. Use `setuptools` (Streamlit Cloud reads `requirements.txt` separately but `pyproject.toml` should remain installable for local dev). Set `requires-python = ">=3.11"`.
3. **Generate `requirements.txt` from `pyproject.toml` runtime deps.** This is what Streamlit Cloud installs. Keep it minimal. Document in the README: "If you add a runtime dep, update both files."
4. `ruff.toml`, `mypy.ini` (strict for `analysis/`, `strategy/`, `portfolio/`, `backtest/`; normal elsewhere), `.pre-commit-config.yaml`.
5. `Makefile`:
   - `install` — `pip install -e .[dev]`
   - `dev` — `streamlit run streamlit_app.py`
   - `test`, `lint`, `fmt`, `typecheck`
   - `refresh-data` — `python scripts/refresh_static_data.py`
   - `clean`
6. `.gitignore`: standard Python + `.venv/`, `.streamlit/secrets.toml` (real secrets file, never committed), `*.pyc`, notebook checkpoints. **Crucially, DO commit the `data/` directory** — the static Parquet files are part of the deploy.
7. `README.md` "Getting Started":
   ```
   git clone <repo>
   cd trading-agent-compass
   python -m venv .venv && source .venv/bin/activate
   pip install -e .[dev]
   # Required for local dev: copy example secrets, set APP_PASSWORD + API keys
   cp .streamlit/secrets.toml.example .streamlit/secrets.toml  # then edit it
   python scripts/refresh_static_data.py
   streamlit run streamlit_app.py
   ```

### Step 2 — Config system

1. **`config/universe.yaml`:**
   ```yaml
   etfs: [QQQ, QLD, TQQQ, SQQQ]
   single_names: [MSFT, GOOGL, NVDA, AAPL, AMZN, META]
   benchmarks: [SPY, VOO]
   ```

2. **`config/strategy_params.yaml`** — bucket definitions and placeholder regime thresholds. Comments explain what each threshold does, even though Phase 0 doesn't use them yet.

3. **`config/profiles/{conservative,moderate,aggressive}.yaml`** — three pre-built risk profiles. Each has: `risk_level` (1-10), `aggression` (1-10), `max_leverage` (1.0-3.0), `volatility_tolerance` (low/medium/high), `trading_intensity` (passive/moderate/active), `st_tax_rate` (default 0.32), `lt_tax_rate` (default 0.15), `recurring_contribution` (amount + frequency), `constraints` (list).

4. **`tradeagent/config.py`** — Pydantic Settings classes:
   - `AppConfig` loads + validates all three YAML types
   - Strict validation, loud errors with field paths on missing/invalid fields
   - Settings load once, treated as immutable

5. **`tradeagent/secrets.py`** — key resolution helper:
   ```python
   def get_secret(name: str, *, allow_session: bool = True) -> str | None:
       """
       Resolution order:
         1. st.session_state[name] if allow_session and Streamlit is running
         2. st.secrets[name] if Streamlit is running
         3. os.environ[name]
       Returns None if not found (caller decides if that's an error).
       """
   ```
   Special: `OPENAI_API_KEY` is the only secret where `allow_session=True` matters in practice — for everything else (`APP_PASSWORD`, Tiingo, FRED), the owner sets it once in `st.secrets`.

6. **`.streamlit/secrets.toml.example`:**
   ```toml
   # Owner's keys, set in Streamlit Cloud dashboard for prod deploy.
   # For local dev, copy this to .streamlit/secrets.toml (gitignored) and fill in.

   APP_PASSWORD = "change-me"   # required: visitors enter this before seeing the app
   TIINGO_API_KEY = "..."        # required for news ingestion (Phase 1 onward)
   FRED_API_KEY = "..."          # required for macro data
   # NOTE: OPENAI_API_KEY is NOT set here — visitors paste their own in the sidebar
   ```

7. **`.streamlit/config.toml`** — theme + behavior:
   ```toml
   [theme]
   base = "dark"
   primaryColor = "#3B82F6"
   [browser]
   gatherUsageStats = false
   ```

### Step 3 — Static data store

1. **`tradeagent/data/store.py`** — read/write helpers for:
   - `data/prices/{TICKER}.parquet` — columns `[date, open, high, low, close, adj_close, volume]`, date is tz-aware UTC, dtypes float64 except volume int64
   - `data/fundamentals/{TICKER}.parquet` — long format `[ticker, period_end, fiscal_period, statement_type, metric, value]`
   - `data/macro/{SERIES}.parquet` — columns `[date, value]`
   - `data/corporate_actions/{TICKER}.parquet` — columns `[ticker, ex_date, type, ratio, cash_amount]`
   - `data/news/{TICKER}.parquet` — columns `[id, ticker, published_at, title, url, source, body, hash]`; `published_at` is tz-aware UTC; `hash` is sha256 of url, unique within file

2. Functions:
   - `load_prices(ticker, start=None, end=None) -> pd.DataFrame`
   - `save_prices(ticker, df) -> None`
   - similar for fundamentals, macro, corporate actions, news
   - `load_news(ticker, days=None) -> pd.DataFrame` — optional `days` filters to last N days
   - `save_news(ticker, new_df, rolling_window_days=90) -> None` — merges with existing, dedups by hash, trims to rolling window
   - `list_available_tickers() -> list[str]`
   - `get_last_date(ticker) -> date | None` — for incremental refresh
   - `get_latest_data_date() -> date` — `max(date)` across all price Parquets; used by the freshness banner

3. All functions: documented data shapes per `CLAUDE.md` rule 5. No I/O outside the `data/` directory.

### Step 4 — Ingestion clients

Each client lives in `tradeagent/data/{name}.py`. Same common shape: structured logging, tenacity retry, documented DataFrame shapes, never raises on empty.

**`prices.py` — yfinance:**
- `fetch_daily_bars(ticker, start, end=None) -> pd.DataFrame`
- `fetch_dividends(ticker) -> pd.DataFrame`
- `fetch_splits(ticker) -> pd.DataFrame`
- Handle yfinance quirks: timezone weirdness, occasional empty, missing tickers

**`fundamentals.py` — yfinance:**
- `fetch_quarterly(ticker) -> pd.DataFrame` long format
- `fetch_annual(ticker) -> pd.DataFrame` long format

**`news.py` — Tiingo News client** (cached-news architecture, used by GitHub Actions and Phase 1 sentiment):
- `fetch_articles(ticker, days=7) -> pd.DataFrame` — columns `[id, ticker, published_at (tz-aware UTC), title, url, source, body, hash]`
- Paginated, dedup by URL hash
- Reads `TIINGO_API_KEY` via `secrets.get_secret`
- **Writes results to `data/news/{TICKER}.parquet`** via `tradeagent/data/store.py`
- **Rolling 90-day window:** when writing, merge incoming articles with existing ones, drop entries older than 90 days, dedup by hash
- Idempotent: re-running with the same input window produces no diff

**`macro.py` — FRED + yfinance:**
- `fetch_fred_series(series_id, start) -> pd.DataFrame`
- `fetch_vix(start) -> pd.DataFrame` — uses yfinance `^VIX`
- Common series helper: `fetch_common_macro() -> dict[str, pd.DataFrame]` for DGS10, DGS2, UNRATE, CPIAUCSL, VIX

### Step 5 — CLI

`tradeagent/cli.py` — single Typer app, console script `tradectl`:

- `tradectl config validate` — load and print all configs
- `tradectl refresh prices --ticker QQQ --since 2010-01-01`
- `tradectl refresh prices --universe --since 2010-01-01`
- `tradectl refresh fundamentals --universe`
- `tradectl refresh news --universe --days 7`
- `tradectl refresh macro`
- `tradectl refresh all --since 2010-01-01` (prices/fundamentals/macro since the start date; news always last 7 days regardless of `--since`)
- `tradectl status` — print row counts per Parquet file, last dates, disk usage

All commands use `rich` for output. All refresh commands are idempotent.

`scripts/refresh_static_data.py` is a thin wrapper that calls `tradectl refresh all --since 2010-01-01`. The README points to the script; the script points to the CLI.

### Step 6 — Logging

`tradeagent/logging_config.py`:
- `structlog` configured for stdout JSON (Streamlit Cloud captures stdout in its log viewer)
- Pretty console output when `LOG_LEVEL=DEBUG` or running locally
- Every ingestion logs a summary at end: rows fetched, rows written, duration_ms, errors

### Step 7 — Minimal Streamlit app

**`streamlit_app.py`** at repo root (Streamlit Cloud's entry point):

```python
import secrets as stdlib_secrets
import time
import streamlit as st

from tradeagent.ui.sidebar import render_sidebar
from tradeagent.ui.pages.dashboard import render_dashboard

st.set_page_config(
    page_title="Trading Agent",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _require_password() -> bool:
    """Return True iff the session is authenticated."""
    if st.session_state.get("authed"):
        return True

    st.title("Trading Agent")
    st.caption("Enter the access password to continue.")
    pw = st.text_input("Password", type="password", key="pw_input")
    if st.button("Enter"):
        expected = st.secrets.get("APP_PASSWORD", "")
        if expected and stdlib_secrets.compare_digest(pw, expected):
            st.session_state.authed = True
            st.rerun()
        else:
            time.sleep(1.0)  # rate-limit brute force
            st.error("Incorrect password.")
    return False


if _require_password():
    render_sidebar()       # profile picker, OpenAI key input, cost counter
    render_dashboard()     # main content
```

**`tradeagent/ui/sidebar.py`:**
- Profile dropdown: `conservative` / `moderate` / `aggressive`, stored in `st.session_state.profile_name`
- OpenAI key input: `st.text_input("OpenAI API Key", type="password")` → store in `st.session_state.openai_key`
- "Clear key" button
- Cost counter: `st.session_state.session_cost_usd` (initialized 0, will be updated in Phase 1)
- Status indicators: green check if key set, gray dash otherwise
- **Never echo the key value back** — only show "✓ Key set" or "Not set"
- "Sign out" button that sets `st.session_state.authed = False` and reruns

**`tradeagent/ui/pages/dashboard.py`** (called as a function in Phase 0; can become a Streamlit multipage in Phase 1):
- **First line: call `render_freshness_banner()`** (defined in Step 8 below)
- Header: "Trading Agent — Personal v1"
- Ticker selector (`st.selectbox` over `config.universe.etfs + config.universe.single_names`)
- Date range slider (default last 1 year, max 10 years)
- Load prices from static Parquet via `@st.cache_data(ttl=3600)`
- Show price chart with `st.line_chart`
- Status line: "Loaded N rows for QQQ, last date YYYY-MM-DD"
- Placeholder cards: "Regime: coming in Phase 1", "Signals: coming in Phase 3", "Backtest: coming in Phase 2"

### Step 8 — Freshness banner (Phase 0: data date only)

In Phase 0 the banner shows the data date plus a placeholder "?" for the refresh timestamp. The timestamp piece needs an authenticated GitHub API call because the repo is private — that comes in Phase 1. The function signature is designed so Phase 1 only has to fill in the stub.

**`tradeagent/ui/freshness.py`:**

```python
from datetime import datetime, timezone
import streamlit as st
import pandas as pd

from tradeagent.config import get_config
from tradeagent.data.store import get_latest_data_date


@st.cache_data(ttl=900)  # 15 minutes
def _fetch_last_workflow_run() -> datetime | None:
    """Query GitHub for the most recent successful run of the refresh workflow.

    Phase 0: stubbed to always return None. The banner already handles None
    gracefully (shows '?' for the timestamp).

    Phase 1.5 implements this with an authenticated GitHub REST API call using
    a fine-grained PAT stored in st.secrets['GITHUB_TOKEN'] — required because
    the repo is private.
    """
    return None


def _trading_days_between(a: pd.Timestamp, b: pd.Timestamp) -> int:
    """Count US weekdays between two dates (Mon-Fri). Holidays ignored for v1."""
    return max(0, len(pd.bdate_range(start=a, end=b)) - 1)


def render_freshness_banner() -> None:
    latest = get_latest_data_date()                # date object
    last_run = _fetch_last_workflow_run()           # datetime | None
    now = datetime.now(timezone.utc)

    # Format the data date with weekday
    weekday = pd.Timestamp(latest).day_name()[:3]   # "Mon", "Tue", ...
    data_str = f"Market data through **{latest:%Y-%m-%d}** ({weekday} close)"

    # Format last refresh
    if last_run is None:
        refresh_str = "Last refresh: ?"
    else:
        delta = now - last_run
        hours = int(delta.total_seconds() // 3600)
        refresh_str = f"Last refresh: {hours}h ago" if hours < 24 else f"Last refresh: {delta.days}d ago"

    # Determine staleness
    today_utc = pd.Timestamp(now.date())
    staleness_days = _trading_days_between(pd.Timestamp(latest), today_utc)
    stale = staleness_days > 2

    msg = f"📊 {data_str} · {refresh_str}"
    if stale:
        st.warning(f"⚠️ {msg} — Data may be stale. Owner: check the Actions tab.")
    else:
        st.info(msg)
        if last_run is None:
            st.caption(
                "ℹ️ Live refresh timestamp coming in Phase 1 — requires authenticated "
                "API call for private repos."
            )
```

Notes:
- The data-date computation works with no auth — that's the half of the banner that ships in Phase 0
- `_fetch_last_workflow_run` is intentionally a stub returning `None`. The banner's rendering already handles `None` correctly, so Phase 1 only swaps the function body without changing the contract.
- `httpx` is NOT imported in Phase 0 — added in Phase 1.5 when the real implementation lands
- The caption underneath explains the "?" so users (and you in three weeks) don't wonder if it's broken

Add `deployment` block to `config/strategy_params.yaml` now even though Phase 0 doesn't use it (Phase 1.5 will):
```yaml
deployment:
  github_owner: your-github-username           # owner edits before deploy
  github_repo: trading-agent-compass
  refresh_workflow_filename: refresh-data.yml
```

The Pydantic config model gets a corresponding `DeploymentConfig` class with these three string fields, all required.

### Step 9 — GitHub Actions workflow for data refresh

**`.github/workflows/refresh-data.yml`:**

```yaml
name: Refresh static data
on:
  schedule:
    - cron: '0 6 * * 1-5'   # 06:00 UTC weekdays (~01:00-02:00 ET, pre-premarket)
  workflow_dispatch:         # manual trigger from Actions tab

permissions:
  contents: write

jobs:
  refresh:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'
      - run: pip install -e .
      - name: Refresh
        env:
          TIINGO_API_KEY: ${{ secrets.TIINGO_API_KEY }}
          FRED_API_KEY: ${{ secrets.FRED_API_KEY }}
        run: python scripts/refresh_static_data.py
      - name: Commit and push if changed
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add data/
          if git diff --cached --quiet; then
            echo "No data changes."
          else
            git commit -m "chore: refresh static data $(date -u +%Y-%m-%d)"
            git push
          fi
```

Notes:
- Configure `TIINGO_API_KEY` and `FRED_API_KEY` in repo Settings → Secrets → Actions
- The push triggers Streamlit Cloud to redeploy with fresh data
- `workflow_dispatch` lets you trigger from the Actions tab UI for testing

### Step 10 — Tests

- Unit tests for config loading: valid YAML, invalid YAML (missing field, wrong type, out-of-range)
- Unit tests for each ingestion client using small recorded responses (hand-written fixtures in `tests/fixtures/`)
- Property test: refresh idempotency (mock yfinance to return identical data on two calls, assert Parquet files are byte-identical)
- Smoke test: import `streamlit_app` and verify no top-level errors when `st.runtime` is mocked
- Password gate test: with mocked `st.secrets`, verify wrong password keeps `authed=False`, correct password sets `authed=True`
- **Freshness banner tests:**
  - With a fake `data/prices/` containing data up to today: banner shows non-stale, not yellow
  - With data >2 trading days stale: banner shows yellow warning
  - Default Phase 0 behavior (no mock): `_fetch_last_workflow_run` returns `None`, banner shows "Last refresh: ?" with the explanatory caption
  - With `_fetch_last_workflow_run` mocked to return a datetime 6 hours ago: banner shows "Last refresh: 6h ago" (this test exercises the rendering path that Phase 1.5 will light up)
- News rolling-window test: write 100 days of fake articles, run `save_news` with `rolling_window_days=90`, assert >90-day-old entries are dropped
- Coverage target Phase 0: >75% (mostly I/O glue and UI scaffolding)

### Step 11 — Local verification + first deploy

1. Locally: create `.streamlit/secrets.toml` with `APP_PASSWORD = "dev-password"`, `TIINGO_API_KEY`, `FRED_API_KEY`
2. Edit `config/strategy_params.yaml` to set `deployment.github_owner`, `deployment.github_repo` to your actual values
3. Run `python scripts/refresh_static_data.py` — populates `data/` for the full universe since 2010 (prices + fundamentals + macro) and last 7 days of news
4. Commit `data/` directory to git
5. `streamlit run streamlit_app.py` — verify password gate works, then chart loads, then **freshness banner shows correct data date** (the "Last refresh: ?" placeholder is expected in Phase 0; the caption explains it)
6. Push to GitHub as a **private repo named `trading-agent-compass`**
7. Configure GitHub repo Secrets (Settings → Secrets and variables → Actions): `TIINGO_API_KEY`, `FRED_API_KEY`
8. Manually trigger `Refresh static data` workflow from the Actions tab; confirm it runs green and either commits or reports "No data changes"
9. Sign in to Streamlit Community Cloud, "New app", point to the repo + `streamlit_app.py`. When prompted, **authorize the Streamlit GitHub App to access this specific private repo** (free tier supports private repos)
10. In Streamlit Cloud's "Secrets" panel, paste (use TOML format):
    ```toml
    APP_PASSWORD = "..."        # owner-chosen, share out-of-band with invited users
    TIINGO_API_KEY = "..."
    FRED_API_KEY = "..."
    # GITHUB_TOKEN added in Phase 1.5 for the freshness banner timestamp
    ```
    (Skip OpenAI — visitors paste their own.)
11. Deploy. Wait. Visit the URL. Enter the password. Confirm:
    - Chart loads
    - Freshness banner shows correct data date with "Last refresh: ?" (this is correct for Phase 0)

## Acceptance checklist (all must pass before Phase 1)

- [ ] `streamlit run streamlit_app.py` works locally with password gate active
- [ ] `tradectl config validate` passes on the bundled configs
- [ ] `python scripts/refresh_static_data.py` populates the `data/` directory for the full universe with no manual edits (including `data/news/` for the universe)
- [ ] Running refresh twice produces an empty git diff (idempotent)
- [ ] **App is deployed to Streamlit Community Cloud from a private `trading-agent-compass` repo and reachable at the deploy URL**
- [ ] **Password gate works on the deployed app:** correct password authenticates; wrong password is rejected with a 1-second delay; without auth, no other UI is visible
- [ ] **Freshness banner renders on the deployed app** with correct data date; "Last refresh: ?" placeholder with explanatory caption is expected and correct for Phase 0
- [ ] **Staleness warning** can be triggered by temporarily setting old data (verify yellow banner appears)
- [ ] **GitHub Actions workflow runs successfully** via manual trigger from the Actions tab, and either commits or reports "No data changes"
- [ ] Sidebar accepts an OpenAI key, shows "✓ Key set", never echoes the value, "Clear key" button works
- [ ] `make lint && make typecheck && make test` all green
- [ ] README documents the password gate, refresh schedule, the freshness model (including the Phase 1.5 timestamp followup), secrets configuration, private-repo deploy flow, and local-dev flow
- [ ] No `print()` calls anywhere — everything goes through `structlog`
- [ ] No runtime disk writes from the Streamlit app — the only files written are by the refresh script (run locally or via GitHub Actions)

## What NOT to do in Phase 0

- Do not implement analysis (technical, sentiment, regime — all Phase 1)
- Do not implement strategy or signal logic (Phase 3)
- Do not implement the backtest engine (Phase 2)
- Do not implement actual sentiment / OpenAI calls — just wire the sidebar key input and the cost counter placeholder
- Do not add Postgres, Docker, Redis, Celery, FastAPI, Next.js, any scheduler
- Do not add new top-level dependencies without noting in `PLAN.md § Stack changes log`
- Do not write to disk at runtime in the Streamlit app

## When you're done

1. Commit on `main` (or open a PR if owner prefers PR-based flow)
2. Tick every box in the acceptance checklist
3. Include the live Streamlit Cloud URL in the README
4. Include a short screen recording or screenshots showing: local dev working, refresh script working, deployed URL loading
5. Document any deviations from `PLAN.md` in the commit message AND in `PLAN.md § Stack changes log`
6. Draft `PHASE_1_PROMPT.md` based on `PLAN.md § Phase 1`
7. Stop. Wait for owner review. Do not start Phase 1.