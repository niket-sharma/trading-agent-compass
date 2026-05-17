# CLAUDE.md — Trading Agent (Streamlit Cloud v1)

> This file is read by Claude Code on every session. The project is intentionally small. Resist scope creep.

## Project mission

A **personal, advisory-only** trading assistant, deployed as a single Streamlit app on Streamlit Community Cloud. The goal of v1 is to **find out whether the strategy idea actually works** — and to share a live URL with a friend who can try it using their own OpenAI key.

Scope is deliberately small:
- One deployed Streamlit app (one URL, public)
- One universe to start: **QQQ, QLD, TQQQ, SQQQ**, plus a handful of single names
- Advisory only — the system never places orders. It produces a daily signal report on screen.
- **Bring-your-own OpenAI key:** the user pastes their key in the sidebar; it lives only in `st.session_state` for that session

Once the strategy is validated by a few months of real use and the backtest holds up, plan v2 (production stack with proper hosting, auth, persistent per-user state).

## Owner profile

Senior AI/ML engineer with chemical engineering background. Comfortable with rigorous Python and numerical code. Wants bottom-up explanations with concrete data shapes. Runs on WSL2 + VS Code. Has OpenAI API access. Personal data/API budget around $500/month but prefers to start lean.

## Core principles (do not violate)

1. **Advisory-only, always.** No broker order placement. Ever.
2. **Backtest before trust.** Every strategy parameter is validated on a walk-forward backtest before being used for live signals. No exceptions.
3. **Rules-based, deterministic, debuggable.** Regime classification and signal generation are explicit scoring functions you can step through with a debugger. No ML models in v1.
4. **LLM only where LLMs are best.** OpenAI is used for one job: turning unstructured text (news articles) into structured sentiment scores. Never for portfolio decisions.
5. **User keys never persist.** OpenAI API keys are read from `st.session_state` (entered in the sidebar) or `st.secrets` (for the owner's local/staging use). They are never written to disk, never logged, never echoed back in the UI after entry.
6. **Streamlit Cloud filesystem is ephemeral.** Never write runtime data (signals, cached LLM results from a user's key, portfolio state) to disk. Use `st.session_state` for runtime state and the repo-committed `data/` directory only for *static* historical data shipped with the app.
7. **Tax-lot aware.** Sell recommendations specify which lot and call out short-term vs long-term gains.
8. **Cost-aware.** Show the user a live count of their OpenAI spend during the session. Default sentiment scoring uses cheap models (`gpt-5-mini` at $0.25 / $2.00 per 1M input/output tokens) unless they opt into a stronger model.
9. **Reproducible.** Same inputs → same outputs. LLM calls use `temperature=0`. Sentiment outputs are cached by article hash within the session (`st.session_state.sentiment_cache`).
10. **Gated access.** The app is behind a password (`st.secrets["APP_PASSWORD"]`). Visitors enter the password before they see any UI. The password is shared out-of-band with people the owner explicitly invites.
11. **Freshness transparency.** The app makes its data freshness explicit at all times. Every page shows a banner with: the latest date present in the committed `data/` directory, and (from Phase 1 onward) the timestamp of the most recent GitHub Actions workflow run. Because the repo is private, fetching the workflow run timestamp requires an authenticated GitHub API call using a fine-grained PAT (`st.secrets["GITHUB_TOKEN"]`); this is set up in Phase 1. In Phase 0 the banner shows only the data date — the timestamp shows "?". If the latest data is more than 2 US-trading-days stale, the banner turns yellow with a warning icon. Users should never have to wonder "what 'now' does the system think it is?"

## Deployment model

- **Hosting:** Streamlit Community Cloud (free tier). **Private GitHub repo**, app auto-redeploys on push to `main`. Streamlit Community Cloud supports private repos on the free tier — authorize the Streamlit GitHub App to access the specific repo when deploying.
- **Repo name:** `trading-agent-compass` (private GitHub repo)
- **URL:** something like `https://trading-agent-compass-<owner>.streamlit.app`
- **Access:** password-gated. The owner shares the URL + password with invited users only. No public traffic expected.
- **Each visitor gets independent `st.session_state`.** Concurrent visitors are not expected (single-digit invited users, mostly the owner). The app does not need to optimize for concurrent load.
- **Cold starts:** the app sleeps after ~7 days inactivity; first visitor wakes it (10-30s delay). Acceptable.
- **Resource limit:** 1 GB RAM. The full universe of daily bars 2010-present is well under 100 MB. Backtests fit comfortably in memory.

## Tech stack (kept deliberately minimal)

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.11+ | Standard, what Streamlit Cloud runs |
| UI | Streamlit | Single file (or modular pages), zero ops |
| Storage (static) | CSV + Parquet files in repo `data/` | Historical bars, ships with the deploy |
| Storage (cache) | `st.cache_data` + `st.cache_resource` | Streamlit's built-in memoization |
| Storage (session) | `st.session_state` | Per-user runtime state |
| Data: prices | yfinance | Free, works from Streamlit Cloud |
| Data: fundamentals | yfinance | Free, sufficient for QQQ family |
| Data: news | Tiingo News (~$10/mo, owner's key in `st.secrets`) | Cheap, structured. Free fallback: NewsAPI (limited). |
| Data: macro | FRED (free, owner's key in `st.secrets`) | DGS10, DGS2, etc.; VIX from yfinance |
| LLM | OpenAI (`gpt-5-mini` default, `gpt-5` opt-in) | User pastes their key in sidebar |
| Scheduling | None at runtime — user clicks "Refresh" | Streamlit is request-driven. Daily-bar data is fine without a scheduler. For overnight pre-fetch, run a local CLI script and commit results to the `data/` directory in the repo. |
| CLI (dev only) | Typer, `tradectl` | Used locally to pre-fetch + commit static data |
| Testing | pytest | Standard |
| Lint/format/types | ruff + black + mypy (strict on core modules) | Standard |
| Config | YAML + pydantic-settings | Standard |
| Logging | structlog (stdout only on Streamlit Cloud) | Cloud logs visible in Streamlit's dashboard |

Notebooks live in `notebooks/` for backtest analysis and exploration. They are NOT deployed — only the Streamlit app is.

## Repository layout

```
trading-agent-compass/
├── streamlit_app.py            # Entry point Streamlit Cloud looks for
├── tradeagent/
│   ├── __init__.py
│   ├── config.py               # Pydantic Settings + YAML loader
│   ├── secrets.py              # Helper: read from st.secrets OR session_state OR env
│   ├── data/
│   │   ├── prices.py           # yfinance wrapper
│   │   ├── fundamentals.py
│   │   ├── news.py             # Tiingo News client
│   │   ├── macro.py            # FRED client
│   │   └── store.py            # Read/write CSV/Parquet under data/
│   ├── analysis/
│   │   ├── technical.py        # Indicators + per-ticker technical score
│   │   ├── sentiment.py        # OpenAI-powered news scoring (session-cached)
│   │   └── regime.py           # Rules-based 5-state classifier
│   ├── strategy/
│   │   ├── allocation.py       # Bucket targets given regime + profile
│   │   ├── signals.py          # Per-bucket BUY/SELL/HOLD signals
│   │   ├── tax.py              # Lot selection
│   │   └── safety.py           # Sizing throttles
│   ├── portfolio/
│   │   └── state.py            # Hypothetical portfolio (session-scoped)
│   ├── backtest/
│   │   ├── engine.py           # Walk-forward simulator
│   │   └── metrics.py          # CAGR, drawdown, Sharpe, etc.
│   ├── reporting/
│   │   ├── brief.py            # Daily brief renderer (markdown for Streamlit)
│   │   └── benchmarks.py
│   ├── ui/
│   │   ├── sidebar.py          # API key input, profile selector, refresh button
│   │   ├── freshness.py        # Freshness banner: data date + GitHub last-run timestamp
│   │   ├── pages/
│   │   │   ├── 1_📊_Dashboard.py
│   │   │   ├── 2_🎯_Signals.py
│   │   │   ├── 3_📈_Regime.py
│   │   │   ├── 4_🧪_Backtest.py
│   │   │   └── 5_⚙️_Settings.py
│   │   └── components.py       # Reusable UI components (regime card, signal row, etc.)
│   └── cli.py                  # Dev-only CLI for pre-fetching static data
├── data/                       # Committed to repo: static historical data
│   ├── prices/                 # Parquet per ticker
│   ├── fundamentals/
│   ├── macro/
│   └── news/                   # Parquet per ticker, refreshed by GitHub Actions
├── config/
│   ├── strategy_params.yaml    # Regime thresholds, signal weights, bucket defs
│   ├── universe.yaml           # Tickers
│   └── profiles/               # Pre-built risk profiles (conservative, moderate, aggressive)
│       ├── conservative.yaml
│       ├── moderate.yaml
│       └── aggressive.yaml
├── notebooks/                  # Local-only, not deployed
├── tests/
├── scripts/
│   └── refresh_static_data.py  # Run by GitHub Action or locally; commits data/ updates
├── .github/
│   └── workflows/
│       └── refresh-data.yml    # Scheduled workflow: refresh + commit + push
├── .streamlit/
│   ├── config.toml             # Streamlit theme + behavior
│   └── secrets.toml.example    # Template (real secrets.toml in repo .gitignore, real values in Streamlit Cloud dashboard)
├── CLAUDE.md
├── PLAN.md
├── pyproject.toml
├── requirements.txt            # Streamlit Cloud reads this
└── README.md
```

## Streamlit Cloud specifics

- **Entry point:** `streamlit_app.py` at repo root. Streamlit Cloud auto-detects this.
- **Dependencies:** `requirements.txt` (Streamlit Cloud installs from this). Also keep `pyproject.toml` for local dev + testing.
- **Secrets:** the owner sets `APP_PASSWORD`, `TIINGO_API_KEY`, `FRED_API_KEY` in the Streamlit Cloud secrets UI from Phase 0. **`GITHUB_TOKEN`** (fine-grained PAT for the freshness banner) is added in Phase 1. **`OPENAI_API_KEY` is NOT set by the owner** — visitors paste their own.
- **Password gate:** `streamlit_app.py` checks `st.session_state.authed` first. If false, render only a password prompt that compares against `st.secrets["APP_PASSWORD"]` using a constant-time comparison (`secrets.compare_digest`). On match, set `st.session_state.authed = True` and rerun. Until authed, no other UI renders. The password itself is shared out-of-band with invited users.
- **The `tradeagent/secrets.py` helper** resolves keys in this order:
  1. `st.session_state` (user-pasted, used for `OPENAI_API_KEY`)
  2. `st.secrets` (owner-configured: `APP_PASSWORD`, `TIINGO_API_KEY`, `FRED_API_KEY`, `GITHUB_TOKEN`)
  3. `os.environ` (local dev)
  4. Raise a friendly error
- **No `data_store/` directory written at runtime.** All runtime caching uses `st.cache_data` (in-memory, evicted on app restart). All persistent data lives in the repo's `data/` directory.
- **Static data refresh is automated via GitHub Actions.** A scheduled workflow runs `scripts/refresh_static_data.py`, commits any changed Parquet files back to `main`, which triggers a Streamlit Cloud redeploy. Schedule: weekdays at 06:00 UTC (post-Asian-close, pre-US-premarket). Workflow secrets: `TIINGO_API_KEY`, `FRED_API_KEY` (same values as the Streamlit Cloud secrets).

## Data freshness model

This is the single most important non-obvious behavior of the app, so it gets its own section.

**The app's worldview is always "as of the last successful GitHub Actions run."** The Streamlit process never reaches out to yfinance, FRED, or Tiingo News at request time — it only reads from the committed `data/` directory. This is deliberate: deterministic behavior across visitors, zero per-request API spend on the owner's accounts, and no surprise rate-limit failures during a user session. The cost is staleness — which is bounded but real.

**What refreshes when:**

| Data | Source | Cadence | How |
|---|---|---|---|
| Daily price bars | yfinance | Weekdays 06:00 UTC | GitHub Actions → commit → redeploy |
| Macro series (VIX, DGS10, etc.) | yfinance + FRED | Weekdays 06:00 UTC | Same workflow |
| News articles | Tiingo News | Weekdays 06:00 UTC | Same workflow (cached in `data/news/`, scored offline by the workflow if owner's `OPENAI_API_KEY` is set as a workflow secret, otherwise scored on-demand using visitor's key) |
| Sentiment scores on cached articles | OpenAI | On-demand (visitor clicks "Refresh signals") | Visitor's own key, results cached in `st.session_state.sentiment_cache` |

**Expected staleness windows:**
- Visit at any time on a weekday: data is as of the prior trading day's close (workflow ran that morning)
- Visit on a weekend: data is as of Friday's close
- Visit the morning after a US holiday: data is still as of the prior trading day's close (yfinance had no new bar to deliver; the idempotent commit step produces no push, so no redeploy needed)
- Visit during a GitHub Actions outage: data is as of whenever the workflow last succeeded; the freshness banner makes this visible

**Freshness banner (mandatory, shown on every page):**
Top of every page renders a one-line bar:
> 📊 Market data through **2026-05-15** (Fri close) · Last refresh: 6 hours ago

If `latest_data_date` is more than 2 US-trading-days behind `today_in_ny`, the banner turns yellow with a warning icon and message: "Data may be stale — recent workflow runs may have failed. Owner: check the Actions tab."

**Implementation:**
- Latest data date: computed from `max(date)` across the Parquet files in `data/prices/`, memoized with `@st.cache_data(ttl=900)` (15 minutes). **This works in Phase 0 with no auth required.**
- Last refresh timestamp (Phase 1 onward): queried from GitHub REST API `GET /repos/{owner}/{repo}/actions/workflows/refresh-data.yml/runs?per_page=1`. **Because the repo is private**, this requires authentication via a fine-grained PAT scoped to this repo with `Actions: Read` permission only. Stored as `st.secrets["GITHUB_TOKEN"]` and sent as `Authorization: Bearer <token>`. Authenticated rate limit is 5000 req/hr (well above what we need). Memoized with `@st.cache_data(ttl=900)`.
- In Phase 0 the banner renders with the data date only and a small "?" in place of the timestamp. Phase 1 adds the PAT and lights up the timestamp.
- Repo coordinates (owner/name/workflow filename) are configured in `config/strategy_params.yaml`, not hardcoded.
- If the GitHub API call fails (rate limit, token expired, network), the banner gracefully shows only the data date with "?" — same behavior as Phase 0. Never crash the app.
- **PAT rotation:** the PAT is created with a 365-day expiry (max for fine-grained PATs is shorter; set to maximum allowed). When it expires, the banner reverts to "?" — the app keeps working. The README documents the rotation flow.

**Why not fetch fresh data at request time?**
Considered and rejected for v1. Pros of "fetch live": fresher data, especially news. Cons: every page visit hits yfinance/Tiingo (rate limits, owner's API spend), non-deterministic UX (one visitor sees one set of signals, another sees different), backtest reproducibility undermined. The cached approach makes the system *observable* — every visitor sees the same data, what they see is exactly what the backtest would replay. If freshness becomes a real problem in Phase 5, revisit by adding a "refresh now" button that triggers a `workflow_dispatch` via GitHub API.

## The five buckets

| Bucket | Holdings | Horizon | Purpose |
|---|---|---|---|
| **Base** | QQQ, selected single names | Years | Strategic long-term compounding |
| **2x Leveraged** | QLD | Months to years | Moderate leveraged growth |
| **3x Long-term** | TQQQ (strategic) | Years | Aggressive secular growth, rarely trimmed |
| **3x Medium-term** | TQQQ (tactical) | 1-3 months | Trend cycle swings |
| **3x Short-term** | TQQQ / SQQQ | Days to weeks | Tactical, volatility harvesting |

Bucket weights flex with regime, never fixed. Computation lives in `strategy/allocation.py`.

## The five regimes

Strong Bull → Bull → Neutral → Bear → Strong Bear

Computed by a deterministic scoring function over: 200d trend slope on NDX, 50/200d cross state, VIX level + 20d change, NDX drawdown from 52w high, breadth proxy (% of universe single names above 50d MA), 10y-2y spread, sentiment composite (if user provided an OpenAI key; otherwise excluded from the composite with a UI note).

Thresholds live in `config/strategy_params.yaml` and must be tunable without code changes.

## What "AI" means here

- **OpenAI (`gpt-5-mini` default, `temperature=0`, structured output via Pydantic + `response_format={"type":"json_schema",...}`):**
  - News article → `{score: float[-1,1], confidence: float[0,1], themes: list[str], reasoning: str}` validated with Pydantic
  - The structured-output guarantee means we never have to parse free text
- **Rules-based scoring:** technical indicators → signal score; regime classifier; allocation; safety throttles
- **No ML models in v1.** No HMMs, no gradient boosting, no RL. Adding any of these requires a written design note and is out of scope until v2.

## "Bring your own OpenAI key" UX rules

- Key entry lives in a dedicated sidebar section with a `type="password"` input
- After entry, show a green checkmark + "Key set" — never echo any portion of the key
- A "Clear key" button removes it from session state
- A live cost counter shows estimated spend this session (computed from token usage × per-1M-token prices for the selected model)
- If the user hasn't entered a key, sentiment scoring is skipped gracefully — the regime composite excludes the sentiment component and the UI shows a banner: "Add an OpenAI key for sentiment-aware signals"
- If the user's key fails (invalid, no quota, rate limited), show a clear error in the UI and continue without sentiment

## Workflow rules for Claude Code

1. **Read `PLAN.md` before starting work.** Pick exactly one phase. Do not do more.
2. **Tests are not optional for `analysis/`, `strategy/`, `portfolio/`, `backtest/`.** Coverage target >85% on these modules. Use small Parquet fixture files.
3. **No mock data in production paths.** If an API client needs credentials and they're missing, fail loudly with a UI-friendly message.
4. **Type everything in core modules.** `analysis/`, `strategy/`, `portfolio/`, `backtest/` are mypy strict.
5. **Document data shapes inline:**
   ```python
   def compute_rsi(prices: pd.DataFrame, period: int = 14) -> pd.Series:
       """
       Args:
           prices: DataFrame indexed by tz-aware UTC timestamp,
                   columns ['open','high','low','close','volume'], dtypes float64.
           period: lookback window.
       Returns:
           Series of RSI [0,100], indexed identically to prices,
           first `period` values are NaN.
       """
   ```
6. **Streamlit-specific rules:**
   - Long computations are wrapped in `st.cache_data` (memoize) or shown via `st.spinner`
   - No `print()` — use `structlog`. Logs surface in the Streamlit Cloud dashboard.
   - Never write to disk at runtime. If you find yourself reaching for `open(..., 'w')`, stop and use `st.session_state` or `st.cache_data` instead.
   - Heavy operations (backtest, full sentiment scoring of many articles) are explicitly user-triggered with a button + spinner, not run on every page render.
7. **No new top-level dependencies without justification.** If you really need one, note it in `PLAN.md § Stack changes log`.
8. **Commit messages follow Conventional Commits.**
9. **No look-ahead bias in backtests, ever.**
10. **Cache LLM outputs in session by content hash.** Reruns within a session must not re-spend the user's API budget. Cache lives in `st.session_state.sentiment_cache`.

## Explicitly out of scope for v1

- Broker order placement (any form)
- Multi-user authentication, accounts, billing (anyone with the URL can use it)
- Per-user persistent state (state lives in `st.session_state`, gone when tab closes)
- Postgres, Redis, Docker, Celery, FastAPI, Next.js
- Mobile app
- Options pricing or Greeks engine (PUT recommendations name strike + expiry + approximate cost from yfinance quotes)
- Crypto, futures, FX
- ML models of any kind
- Real-time streaming data
- Scheduled jobs *inside* the Streamlit app (no Celery, no APScheduler). Static-data refresh runs *outside* the app via GitHub Actions — that's allowed and is the only scheduled job.

## Definition of "v1 success"

- App is live at a public URL
- Owner uses it daily for ≥3 months and keeps a written decision journal
- Backtest shows risk-adjusted improvement vs QQQ buy-and-hold across 2015-2024
- At least one friend has tried it end-to-end with their own OpenAI key and reported back
- Cost ceiling held: owner's monthly spend (Tiingo + FRED + occasional own-key OpenAI testing) stays under $50

When all four hold → plan v2 (proper hosting, per-user state, auth).

## Open questions and decisions log

Keep this at the bottom of `PLAN.md`. Surface architectural choices instead of making them silently.