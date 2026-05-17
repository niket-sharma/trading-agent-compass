# PLAN.md — Streamlit Cloud v1 Roadmap

> Read `CLAUDE.md` first. The goal of v1 is to **find out if the strategy idea works** AND share it as a live URL. Five phases. Each ends with something deployed.

## Sequencing principle

Hard dependency chain:

> static data → analysis → backtest → strategy → Streamlit UI → deploy

The backtest engine ships in Phase 2 (early). Every strategy parameter from Phase 3 onward must be validated against the backtest before going into the live signal display.

Each phase ends with a working, committable deliverable. Do not start phase N+1 until phase N's acceptance criteria are met.

Important Streamlit Cloud constraint: **runtime filesystem is ephemeral**. All persistent data ships in the repo's `data/` directory and is refreshed by a scheduled GitHub Actions workflow that commits Parquet updates back to `main`, triggering a redeploy. The Streamlit app itself never writes to disk at runtime.

---

## Phase 0 — Foundations and first deploy

**Goal:** A minimal Streamlit app deployed to Streamlit Community Cloud from a private GitHub repo (`trading-agent-compass`), reachable at a URL the owner shares with invited users. It loads static price data from the repo and shows a chart. No analysis logic yet, but the deployment loop works end-to-end.

**Deliverables:**

1. **Repo scaffold** matching `CLAUDE.md § Repository layout`. `__init__.py` in every package.

2. **`pyproject.toml`** with the locked stack:
   - Runtime: `streamlit>=1.30`, `pydantic>=2`, `pydantic-settings`, `pyyaml`, `structlog`, `pandas`, `numpy`, `yfinance`, `pyarrow`, `httpx`, `tenacity`, `typer`, `rich`, `openai>=1.30`
   - Dev: `pytest`, `pytest-cov`, `freezegun`, `ruff`, `black`, `mypy`, `types-pyyaml`
3. **`requirements.txt`** generated from `pyproject.toml` (Streamlit Cloud reads this). Keep it minimal — only runtime deps.

4. **Tooling:** `ruff.toml`, `mypy.ini` (strict for `analysis/`, `strategy/`, `portfolio/`, `backtest/`), `.pre-commit-config.yaml`, `Makefile` (`install`, `test`, `lint`, `fmt`, `typecheck`, `dev` to run streamlit locally, `refresh-data`).

5. **Config system:**
   - `config/universe.yaml` — etfs (QQQ, QLD, TQQQ, SQQQ), single_names (MSFT, GOOGL, NVDA, AAPL, AMZN, META), benchmarks (SPY, VOO)
   - `config/strategy_params.yaml` — bucket definitions, regime thresholds (placeholders with comments), signal weights (placeholders)
   - `config/profiles/{conservative,moderate,aggressive}.yaml` — pre-built risk profiles (risk_level, aggression, max_leverage, volatility_tolerance, trading_intensity, st_tax_rate, lt_tax_rate, constraints). The user picks one in the sidebar — no custom profile editor in v1.
   - `tradeagent/config.py` — Pydantic Settings classes with strict validation
   - `tradeagent/secrets.py` — key resolution helper (session → st.secrets → env → friendly error)

6. **Static data store (`tradeagent/data/store.py`):**
   - Read/write helpers for Parquet under `data/prices/{TICKER}.parquet`, `data/fundamentals/{TICKER}.parquet`, `data/macro/{SERIES}.parquet`, `data/news/{TICKER}.parquet`
   - Schema documented inline
   - All files committed to repo — Streamlit Cloud serves them on each deploy

7. **Ingestion clients** (used by the local CLI and GitHub Actions, not by the Streamlit app at runtime):
   - `prices.py` — yfinance: daily bars, dividends, splits
   - `fundamentals.py` — yfinance: quarterly + annual financials
   - `news.py` — Tiingo News client; **writes results to `data/news/{TICKER}.parquet`** (cached-news architecture). Idempotent upsert keyed by article hash. Rolling window: keep last 90 days, drop older entries (keeps repo size bounded).
   - `macro.py` — FRED + VIX from yfinance

8. **CLI for static data refresh (`tradeagent/cli.py` + `scripts/refresh_static_data.py`):**
   - `tradectl refresh prices --universe` — pulls latest yfinance data, writes to `data/prices/`
   - `tradectl refresh fundamentals --universe`
   - `tradectl refresh news --universe --days 7` — fetches last 7 days of news per ticker, merges into existing `data/news/`, trims to 90-day window
   - `tradectl refresh macro`
   - `tradectl refresh all`
   - `tradectl config validate`
   - Idempotent — running twice produces no diff on disk if no new data

9. **Minimal Streamlit app (`streamlit_app.py`):**
   - **Password gate first.** Before any other UI renders, check `st.session_state.authed`. If false, render a single password input; on submit, compare with `st.secrets["APP_PASSWORD"]` using `secrets.compare_digest`. On match, set `st.session_state.authed = True` and `st.rerun()`. On mismatch, show an error and rate-limit by sleeping 1 second.
   - Sidebar (visible only after auth): "Pick a profile" dropdown (conservative/moderate/aggressive), "Paste OpenAI key" password input (stored in `st.session_state.openai_key`), "Clear key" button, current session cost counter (shows $0.00 in Phase 0)
   - Main page (visible only after auth): freshness banner at top, "Hello" header, ticker selector, price chart for QQQ from static Parquet data, "Loaded N rows, last date Y" status line
   - `st.cache_data` on the load function (TTL 1 hour)

10. **Freshness banner — Phase 0 version (`tradeagent/ui/freshness.py`):**
    - Function `render_freshness_banner()` called at the top of every page (or in a shared layout wrapper)
    - Computes `latest_data_date` = `max(date)` across all Parquet files under `data/prices/`, memoized with `@st.cache_data(ttl=900)` (15 minutes). **No auth needed.**
    - Renders a one-line banner: `📊 Market data through **YYYY-MM-DD** (Day close) · Last refresh: ?`
    - The "?" is intentional and explained by a tooltip: "Live refresh timestamp coming in Phase 1 (requires authenticated API call for private repos)."
    - **Staleness rule:** if `latest_data_date` is more than 2 US-trading-days behind today (use `pandas.tseries.offsets.BDay` or a simple NYSE weekday check; full holiday calendar deferred), render the banner with a yellow background and warning icon. Message: "Data may be stale — owner: check the Actions tab."
    - The function has a placeholder `_fetch_last_workflow_run() -> datetime | None` stub that always returns `None` in Phase 0. Phase 1 implements it. The banner rendering already handles `None` correctly.
    - Repo coordinates (`github_owner`, `github_repo`, `refresh_workflow_filename`) configured in `config/strategy_params.yaml` under a `deployment:` block — populated now even though only used in Phase 1.

11. **GitHub Actions workflow (`.github/workflows/refresh-data.yml`):**
    - Schedule: `cron: '0 6 * * 1-5'` (06:00 UTC weekdays, before US premarket)
    - Steps: checkout, set up Python 3.11, `pip install -e .`, run `python scripts/refresh_static_data.py` (which calls `tradectl refresh all` — covers prices, fundamentals, macro, and news), `git add data/`, commit only if there are changes (`git diff --cached --quiet || git commit -m "chore: refresh static data $(date -u +%Y-%m-%d)"`), push
    - Secrets used: `TIINGO_API_KEY` (news), `FRED_API_KEY` (macro) — set in GitHub repo settings → Secrets
    - Permissions: `contents: write` on the workflow
    - Include `workflow_dispatch:` so the workflow can also be run manually from the Actions tab
    - The commit message uses a fixed format so it's easy to filter in git log

12. **Deploy:**
    - Push repo to GitHub as a **private repo** (the repo contains `universe.yaml`, `strategy_params.yaml`, and a decision-revealing commit history — keep private)
    - Connect Streamlit Community Cloud to the repo, deploy from `main`. When prompted, authorize the Streamlit GitHub App to access this specific private repo. Free tier supports private repos.
    - Configure Streamlit Cloud secrets: `APP_PASSWORD` (owner-chosen, shared out-of-band with invited users), `TIINGO_API_KEY`, `FRED_API_KEY`. (`GITHUB_TOKEN` is added in Phase 1.)
    - Configure the same `TIINGO_API_KEY` and `FRED_API_KEY` in GitHub repo Secrets for the refresh workflow
    - Manually trigger the refresh workflow once from the Actions tab to verify it commits and pushes correctly
    - Verify the deployed URL: enter password → see the QQQ chart + freshness banner showing correct data date (timestamp shows "?")

13. **README** with:
    - The live URL (placeholder until deploy) and note about password gate
    - **"How fresh is the data?" section** explaining the cadence: workflow runs weekdays at 06:00 UTC, data is as of prior trading day's close, weekends show Friday's close
    - "How to run locally" (`streamlit run streamlit_app.py`)
    - "How to refresh static data" (auto via GitHub Actions weekdays; manual via Actions tab or `python scripts/refresh_static_data.py`)
    - "How to deploy" (push to main; static data refreshes commit straight to main)

**Acceptance criteria:**

- [ ] `streamlit run streamlit_app.py` works locally and shows the QQQ chart (with `APP_PASSWORD` in local `.streamlit/secrets.toml`)
- [ ] `python scripts/refresh_static_data.py` populates `data/prices/`, `data/fundamentals/`, `data/macro/`, `data/news/` with no manual edits
- [ ] Running refresh twice produces an empty git diff
- [ ] App is deployed to Streamlit Community Cloud from a **private** GitHub repo and reachable at the deploy URL
- [ ] **Password gate works:** visiting the URL shows only a password prompt; wrong password is rejected with a delay; correct password reveals the app
- [ ] **Freshness banner renders correctly** showing data date (timestamp shows "?" with a tooltip — populated in Phase 1)
- [ ] **Staleness warning fires** when tested with mocked stale data (latest date >2 trading days behind today → yellow banner)
- [ ] **GitHub Actions workflow runs successfully** at least once (manual trigger), updates `data/`, commits, pushes, and triggers a Streamlit Cloud redeploy
- [ ] Sidebar accepts an OpenAI key, shows green checkmark, never echoes the key value
- [ ] `make lint && make typecheck && make test` all pass
- [ ] README documents the password gate, refresh schedule, **private-repo deploy flow**, freshness behavior, and local-dev flow

**Estimated effort:** 6-9 days (Phase 0 freshness banner is simpler without the auth piece; offset by ~half a day for the private-repo deploy step).

---

## Phase 1 — Analysis modules

**Goal:** Pure-functional modules consumed by the Streamlit app. The app gains a working regime + technical view.

**Deliverables:**

### 1.1 Technical analysis (`tradeagent/analysis/technical.py`)
- Indicators: SMA, EMA, VWAP, RSI, MACD, Bollinger Bands, ATR
- Trend: 50/200 slope, golden/death cross
- Momentum: 30d, 90d, 1y, 3y returns; rolling Sharpe
- Volatility: realized vol, vol-of-vol
- Per-ticker daily technical score in `[-1, 1]` with component breakdown returned as a dict
- All functions pure: `(DataFrame) -> Series/DataFrame`. No I/O.

### 1.2 Sentiment analysis (`tradeagent/analysis/sentiment.py`)

**Architecture (Option A, locked in):** news articles are pre-fetched into `data/news/{TICKER}.parquet` by the GitHub Actions workflow (already wired in Phase 0). Sentiment scoring runs **on demand**, on the cached articles, using the **visitor's OpenAI key**. The article fetch and the scoring are decoupled.

- **OpenAI client wrapper** with retry + cost tracking
- Uses `gpt-5-mini` by default; `gpt-5` opt-in via sidebar setting
- **Pricing constants** in module top-level dict: `{"gpt-5-mini": (0.25, 2.00), "gpt-5": (TBD, TBD)}` — per 1M input/output tokens. Owner updates when OpenAI changes prices.
- **Structured output** via `response_format={"type":"json_schema",...}` with Pydantic schema for `{score, confidence, themes, reasoning}`. Never parse free text.
- `temperature=0` for reproducibility
- **Session caching:** before calling, check `st.session_state.sentiment_cache` keyed by SHA256 of `(article_hash, model_name)`. Hit → return cached. Miss → call, store result + cost.
- **Cost tracking:** after each call, compute cost from token counts and the pricing dict. Add to `st.session_state.session_cost_usd`.
- **No key → no sentiment:** if `st.session_state.openai_key` is unset, return neutral sentiment with `confidence=0` and a flag indicating "skipped: no key". The regime classifier excludes the sentiment component when this happens. The dashboard shows a banner inviting the user to add a key.
- Per-ticker daily aggregate: volume-weighted recent articles, decay older articles
- **Read articles from `data/news/{TICKER}.parquet`, never from a live Tiingo call.** This is what the "cached news" decision means in practice. The freshness banner already tells the user how recent the news is; sentiment runs on whatever is there.

### 1.3 Regime classifier (`tradeagent/analysis/regime.py`)
- Inputs (all as of date T, no look-ahead): NDX 200d slope, 50/200 cross state, VIX level + 20d change, NDX drawdown from 52w high, breadth proxy (% of universe single names above 50d MA), 10y-2y spread, sentiment composite (or excluded if no key)
- Output: `RegimeReading(date, regime, score, components, regime_age_days, sentiment_included: bool)`
- Scoring rubric explicit and documented inline; thresholds from `strategy_params.yaml`
- Pure function — caller decides whether to display/cache

### 1.4 Streamlit pages (`tradeagent/ui/pages/`)
- **3_📈_Regime.py** — current regime card, component scores, history timeline overlaid on QQQ. A "Score N latest articles for sentiment" button calls sentiment scoring with a spinner, uses the user's key, updates the regime display.
- Dashboard placeholder is updated to show the regime card at the top.

### 1.5 Freshness banner — full version (`tradeagent/ui/freshness.py`)
Now that Phase 0 has the data-date side working, fill in the GitHub API piece:
- **Create a fine-grained PAT** in GitHub Settings → Developer Settings → Personal access tokens → Fine-grained tokens
  - Resource owner: the owner's GitHub account
  - Repository access: select **only** `trading-agent-compass`
  - Permissions → Repository → **Actions: Read-only** (and nothing else)
  - Expiry: maximum allowed (currently 1 year). Diary a reminder to rotate.
- **Where the PAT goes:** the PAT is **only** consumed by the Streamlit app for the freshness banner. The GitHub Actions workflow itself uses the auto-provided `${{ secrets.GITHUB_TOKEN }}` and does NOT need this PAT. So:
  - Streamlit Cloud secrets: add `GITHUB_TOKEN = "<the PAT value>"` alongside `APP_PASSWORD`, etc.
  - Local `.streamlit/secrets.toml`: same key, same value (for local dev parity)
  - GitHub repo Secrets: no change — the workflow already has what it needs
- Implement `_fetch_last_workflow_run()`:
  ```python
  @st.cache_data(ttl=900)
  def _fetch_last_workflow_run() -> datetime | None:
      cfg = get_config()
      token = get_secret("GITHUB_TOKEN", allow_session=False)
      if not token:
          return None
      url = (
          f"https://api.github.com/repos/{cfg.deployment.github_owner}"
          f"/{cfg.deployment.github_repo}/actions/workflows"
          f"/{cfg.deployment.refresh_workflow_filename}/runs"
          "?per_page=1&status=success"
      )
      try:
          r = httpx.get(
              url,
              headers={
                  "Authorization": f"Bearer {token}",
                  "Accept": "application/vnd.github+json",
                  "X-GitHub-Api-Version": "2022-11-28",
              },
              timeout=5.0,
          )
          r.raise_for_status()
          runs = r.json().get("workflow_runs", [])
          if not runs:
              return None
          return datetime.fromisoformat(runs[0]["updated_at"].replace("Z", "+00:00"))
      except Exception:
          return None
  ```
- Banner now shows "Last refresh: Nh ago" when the call succeeds, "?" when it fails (token missing, expired, rate-limited, network error)
- Add a news-freshness line on regime/signal pages: "News articles through YYYY-MM-DD (N articles in last 7d)"
- **Test the failure modes:** missing token → "?"; bad token → "?"; valid token → timestamp shows

**Acceptance criteria:**

- [ ] >85% test coverage on `technical.py`, `sentiment.py`, `regime.py` with Parquet fixtures
- [ ] Regime classifier on 2015-2024 static data produces sensible labels: bear in late 2018, strong bear in March 2020, bear most of 2022, bull 2023-2024. **Documented in `notebooks/01_regime_validation.ipynb` with charts overlaid on QQQ.**
- [ ] Sentiment module: same article hash → identical score on rerun within a session
- [ ] Session cost counter in sidebar updates after each sentiment call
- [ ] Deployed app shows the regime page working end-to-end; with no OpenAI key, regime still computes (sentiment excluded, UI banner shown)
- [ ] Hitting an invalid OpenAI key produces a clear UI error and graceful fallback
- [ ] **Freshness banner now shows a real "Last refresh: Nh ago" timestamp** on the deployed app
- [ ] **GitHub PAT failure is graceful** — banner falls back to "?" if token missing/expired/rate-limited
- [ ] README documents the PAT creation flow, scopes, rotation reminder

**Estimated effort:** 8-11 days (added ~1 day for the PAT setup + auth code + failure-mode tests).

---

## Phase 2 — Backtest engine

**Goal:** Walk-forward simulator. Strategy without backtest is gambling. Do not skip, do not rush. Runs entirely in the Streamlit app — user clicks "Run backtest" and sees results in 10-30 seconds.

**Deliverables:**

1. **Backtest harness (`tradeagent/backtest/engine.py`):**
   - Walks day-by-day through static historical data in `data/prices/`
   - At each day T, calls regime + analysis modules using only data ≤ T (enforced)
   - Maintains a hypothetical portfolio with lots, cash, tax tracking — all in-memory dataclasses, no disk writes
   - Records every decision with reasoning trace
   - Output is a `BacktestResult` dataclass returned to the caller

2. **Tax-lot simulator:** FIFO, LIFO, HIFO selection. Tracks ST vs LT gains (>365d = LT).

3. **Leveraged ETF simulator:** model daily rebalance decay path-dependently for TQQQ/SQQQ. Validate against actual TQQQ history in a notebook (`notebooks/02_tqqq_simulation_validation.ipynb`).

4. **Performance metrics (`tradeagent/backtest/metrics.py`):** CAGR, max drawdown, Sharpe, Sortino, Calmar, win rate, tax drag.

5. **Benchmark comparison:** vs QQQ buy-and-hold, vs TQQQ buy-and-hold, vs 60/40.

6. **Walk-forward:** train (parameter tune) on 2015-2019, test on 2020-2024 out-of-sample. Report metrics separately.

7. **Named scenario tests in `tests/scenarios/`:** `test_2018_q4_drawdown`, `test_2020_covid_crash`, `test_2022_bear`, `test_2023_recovery`.

8. **Streamlit backtest page (`4_🧪_Backtest.py`):**
   - User picks: profile, start date, end date, initial capital
   - "Run backtest" button → spinner → results
   - Results: equity curve, drawdown chart, regime overlay, metrics table, benchmark comparison table, decision log (expandable)
   - Cache results in `st.session_state.backtest_results` keyed by parameters so the same backtest doesn't re-run

**Acceptance criteria:**

- [ ] QQQ buy-and-hold backtest matches actual QQQ total return within 0.5% over 2015-2024
- [ ] TQQQ daily-rebalance simulation matches actual TQQQ within 2% over 2015-2024
- [ ] **No-lookahead property test:** randomly truncate input data at day T, assert decisions for days < T are byte-identical to a full-data run
- [ ] Full 10-year backtest of the Phase 3 strategy (when it exists) runs in under 30 seconds on Streamlit Cloud
- [ ] Backtest page renders results cleanly on phone portrait orientation

**Estimated effort:** 8-12 days. Slow down here.

---

## Phase 3 — Strategy

**Goal:** Given regime + analysis + user profile, produce per-bucket BUY/SELL/HOLD signals with sizing and tax-lot selection. Wired into both the backtest and the live signals page.

**Deliverables:**

### 3.1 Allocation engine (`tradeagent/strategy/allocation.py`)
- `(regime, profile, current_portfolio, drawdown) -> target_bucket_weights`
- Smooth transitions (EMA-smoothed targets)
- Respect profile constraints
- Return reasoning trace

### 3.2 Signal generator (`tradeagent/strategy/signals.py`)
- Per-bucket logic per `CLAUDE.md § The five buckets`
- Each signal: `Signal(action, ticker, bucket, quantity, limit_price, urgency, confidence, reasoning_dict)`

### 3.3 Tax-aware sell prioritization (`tradeagent/strategy/tax.py`)
- HIFO by default, switch to tax-loss harvesting when opportunity exists
- Wash sale flag (advisory)
- Sells specify lot ID

### 3.4 Hedging (`tradeagent/strategy/safety.py` + part of `signals.py`)
- Triggers in Strong Bear with high regime confidence
- Recommends ~30d ATM-to-5%-OTM QQQ PUT, sized 30-50% of long leveraged exposure
- Strike + expiry + approx cost from yfinance options chain
- Exit logic: regime improvement or 50% profit

### 3.5 Safety overlay (`tradeagent/strategy/safety.py`)
- Consecutive-loss throttle
- Volatility throttle (VIX > threshold)
- Confidence throttle (regime near transition)
- All throttles multiply size; never override direction

### 3.6 Signals page (`2_🎯_Signals.py`)
- For the user's selected profile + the current regime computed from the latest static data, show today's recommended signals
- Each signal: action, ticker, bucket, quantity (in % of portfolio since we don't know their capital), limit price, urgency, expandable reasoning
- "Refresh data" button at top — calls yfinance for the latest bars, recomputes (use `st.cache_data` with TTL ~15min during market hours)
- If no OpenAI key, sentiment-driven nuances are excluded with a banner

**Acceptance criteria:**

- [ ] Backtest 2015-2024 shows **risk-adjusted** outperformance vs QQQ buy-and-hold (higher Sharpe, lower max DD). Absolute return is stretch.
- [ ] 2022 backtest: max drawdown < 40%
- [ ] 2020 COVID backtest: hedge recommended in late Feb or early March
- [ ] No NaN-propagated signals — bad data fails loudly
- [ ] Signals page works on the deployed app for a visitor with no key

**Estimated effort:** 8-12 days.

---

## Phase 4 — Polish and share

**Goal:** Make it good enough to share. README, onboarding flow, error handling, cost transparency.

**Deliverables:**

1. **First-time visitor experience:**
   - When session has no profile selected, show a welcome screen explaining what the app is, the BYO-key model, and a "Get started" button
   - Profile selector defaults to "moderate"
   - Tooltip on every regime / signal component explaining what it measures

2. **OpenAI key UX polish:**
   - Validate key with a tiny test call when entered ("Verifying...")
   - Show estimated cost per refresh ("This refresh will use ~$0.02 of your OpenAI credit")
   - "Skip sentiment" button for users without a key

3. **Settings page (`5_⚙️_Settings.py`):**
   - View current profile values (read-only in v1 — custom editing is v2)
   - Toggle: `gpt-5-mini` (default) vs `gpt-5`
   - View session cost breakdown
   - Reset session

4. **Error handling pass:**
   - All yfinance failures → user-visible error + retry button
   - All OpenAI failures → user-visible error, regime falls back to no-sentiment mode
   - No tracebacks ever shown to users — they go to logs only
   - Empty / stale static data → banner "Data last refreshed YYYY-MM-DD, owner needs to refresh"

5. **README upgrade:**
   - Screenshot of the deployed app
   - "Try it" section with the URL
   - "Bring your own OpenAI key" explanation (where to get one, expected cost ~$X per session)
   - Disclaimers: advisory only, not financial advice, leveraged ETFs are dangerous, etc.
   - Owner's contact for feedback

6. **Telemetry-lite:** optional, opt-in `st.toast` after generating signals: "Anonymous usage logged" — no PII, just counts. If owner doesn't want this, skip. Otherwise use Streamlit Cloud's built-in analytics.

**Acceptance criteria:**

- [ ] A friend visits the URL, pastes their OpenAI key, picks a profile, sees a regime view + today's signals + can run a backtest, in under 5 minutes
- [ ] No traceback ever surfaces to the user
- [ ] Owner has shared the URL with at least one friend and gotten feedback
- [ ] Disclaimers prominent on landing page and signals page

**Estimated effort:** 4-6 days.

---

## Phase 5 — Use it, validate, decide on v2 (3-6 months, not a build phase)

Same as in the prior plan. Daily use, decision journal, monthly review, tune `strategy_params.yaml` only after issues are reproducible in backtest.

**Definition of "v1 worked":**

- App live and used daily by owner for 3+ months
- Backtest still shows risk-adjusted improvement vs QQQ buy-and-hold
- At least one friend tried it end-to-end with own key and gave feedback
- Costs stayed under $50/month for the owner

**If v1 worked:** plan v2 — proper hosting (probably leaves Streamlit Cloud for higher RAM + persistent user state), Postgres for per-user portfolios, optional auth, maybe broker integration.

**If v1 didn't work:** the rules-based regime + signal approach is likely wrong for your style. Reconsider before adding ML — most "ML will fix it" answers turn out to be "I had no edge to begin with."

---

## Stack changes log

_Add an entry every time a new dependency is added or an architectural decision is revised._

| Date | Change | Reason |
|---|---|---|
| 2026-05-17 | Locked in **cached-news architecture** (Option A): articles pre-fetched by GitHub Actions into `data/news/`, sentiment scoring runs on cached articles at request time using visitor's OpenAI key. | Deterministic behavior across visitors; no per-visit Tiingo spend; sentiment is a slow-moving composite anyway, so daily freshness is sufficient for daily-bar strategy. Revisit if signal-driving news becomes time-sensitive. |
| 2026-05-17 | Added **freshness banner** as a Phase 0 deliverable. Banner queries GitHub REST API for last successful workflow run. | Prevents silent staleness — users always know what "now" the system thinks it is. Particularly important for shared deployment where visitors won't know the refresh cadence. |
| 2026-05-17 | Repo is **private**, named `trading-agent-compass`. Freshness banner ships data-date-only in Phase 0; authenticated timestamp lookup added in Phase 1.5 via fine-grained PAT. | Universe + strategy + commit history reveal owner's positions and reasoning; keep private. Deferring the PAT keeps Phase 0 simple — banner is still useful with just the data date, and the auth piece batches naturally with other Phase 1 freshness changes. |

---

## Open questions

1. **OpenAI pricing constants:** hardcoded in `sentiment.py` as `{"gpt-5-mini": (0.25, 2.00)}` (per 1M input/output tokens). Owner updates when OpenAI changes prices. Acceptable for v1.
2. **PUT pricing source:** yfinance options chain (delayed, free). Acceptable for advisory-only.
3. **Profile customization:** v1 ships 3 fixed profiles. Custom profile editor is explicitly v2.
4. **Recurring contribution simulation in backtest:** default monthly $1000. Adjustable in profile YAML.
5. **Backtest fees/slippage:** default $0 commission, 1 bp slippage on QQQ/QLD, 3 bp on TQQQ/SQQQ.
6. **Single-name breadth proxy:** % of `universe.yaml` single names above 50d MA. Full NDX-100 breadth deferred.
7. **GitHub Actions refresh frequency:** Phase 0 default is 06:00 UTC weekdays. Owner may adjust later (e.g. multiple times per day during market hours) — flag for Phase 4 if signal freshness becomes an issue.
8. **Sharing the password:** owner shares `APP_PASSWORD` out-of-band (text, email, signal). Rotation strategy is "change it in Streamlit Cloud secrets when you want to revoke access." Acceptable for v1.
9. **News rolling window:** v1 keeps last 90 days of articles in `data/news/`. Keeps repo size bounded. If sentiment composite needs longer history, increase the window.
10. **PAT rotation:** fine-grained GitHub PAT for the freshness banner expires after 1 year (max). When it expires, the banner reverts to "?" — app still works. Owner needs a calendar reminder to rotate. Acceptable for v1.
11. **News source fallback:** Tiingo News is the primary. If owner doesn't want to fund Tiingo, switch to NewsAPI free tier (100 req/day, sufficient for a few tickers per day). The cached-news architecture means either works — only the `news.py` client changes.