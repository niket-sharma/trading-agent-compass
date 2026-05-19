# Trading Agent Compass

**Author:** Niket Sharma · [sharma.niket@gmail.com](mailto:sharma.niket@gmail.com)

Personal advisory-only trading assistant. Regime-based allocation signals for QQQ / QLD / TQQQ / SQQQ and a handful of single names, deployed on Streamlit Community Cloud.

**Advisory only — this system never places orders.**

---

## Live App

> URL: _(update after Streamlit Cloud deploy)_
>
> Access: password-gated. Contact the owner for the password.

---

## What the app does

The app answers one question each trading day: **given where the market is right now, what should my QQQ-family portfolio look like?**

It does this in three sequential steps:

### 1. Regime classification

`tradeagent/analysis/regime.py`

The market is classified into one of five states: **Strong Bull → Bull → Neutral → Bear → Strong Bear**. This is a deterministic weighted scoring function — no ML. Every input and weight is visible and debuggable.

Seven indicators are scored on a [-1, 1] scale and combined into a composite:

| Indicator | What it measures | Weight |
|---|---|---|
| NDX 200d trend slope | Annualised slope of a 200-day regression on QQQ | ~22% |
| 50/200 MA cross | Golden cross (+1) vs death cross (-1) | 20% |
| VIX level | Low (<15) = calm, Extreme (>35) = panic | ~13% |
| VIX 20d change | Rising VIX = bearish momentum | 10% |
| NDX drawdown | Distance from 52-week high | ~9% |
| Breadth | % of single-name universe above their 50d MA | 15% |
| Yield curve | 10y − 2y Treasury spread; inversion = bearish | 10% |
| Sentiment _(optional)_ | News sentiment via OpenAI; only when key is present | +15% redistributed |

**Composite breakpoints:** ≥ 0.60 → Strong Bull · ≥ 0.20 → Bull · ≥ −0.20 → Neutral · ≥ −0.60 → Bear · below → Strong Bear.

All thresholds live in `config/strategy_params.yaml` — tunable without code changes.

### 2. Signal generation

`tradeagent/strategy/`

Given the regime, the system computes **target bucket weights** for the portfolio, then compares them to the current weights to produce BUY / SELL / HOLD signals.

**The five buckets:**

| Bucket | Ticker | Horizon | Purpose |
|---|---|---|---|
| Base | QQQ | Years | Strategic long-term compounding |
| 2x Leveraged | QLD | Months–years | Moderate leveraged growth |
| 3x Long-term | TQQQ | Years | Aggressive secular growth, rarely trimmed |
| 3x Medium-term | TQQQ | 1–3 months | Trend cycle swings |
| 3x Short-term | TQQQ / SQQQ | Days–weeks | Tactical; flips to SQQQ in Bear/Strong Bear |

**How allocation works** (`allocation.py`):
- Base allocation by regime comes from the chosen risk profile (conservative / moderate / aggressive), stored in `config/profiles/*.yaml`.
- A **drawdown throttle** cuts leveraged bucket targets proportionally when the portfolio is more than 15% underwater (severity scales linearly to 50% reduction at −35% drawdown).
- **EMA smoothing** (α = 0.2 default) blends the new target 20% into the current allocation each step — avoids whipsaw rebalancing.

**Signal ordering** (`signals.py`):
- Only buckets with a weight delta > 5% generate a signal (avoids micro-trades).
- Sells are executed before buys (free up cash first).
- Urgency: > 15% delta → High · > 8% → Medium · otherwise Low.
- Confidence blends regime conviction with the ticker's technical score from `analysis/technical.py`.

**Safety throttles** (`safety.py`) — applied after signal generation, they scale `target_pct` down but never change direction:
- **VIX throttle:** above VIX 30, leveraged bucket sizes are reduced (max 70% reduction at VIX 40).
- **Consecutive loss throttle:** three consecutive losing trades → next signal halved.
- **Regime boundary throttle:** composite score within 0.10 of a breakpoint → reduce by 30% (less conviction near the edge).

### 3. Backtesting

`tradeagent/backtest/`

Walk-forward simulation from 2015 to 2024. The engine replays history day-by-day using the same regime → allocation → signal pipeline that runs live.

Key design choices:
- **No lookahead:** at each day T, the engine only passes data with `date ≤ T` to the regime and signal functions. The no-lookahead guarantee is enforced structurally, not by convention.
- **Tax-lot tracking:** lots are created on every buy and selected for sale using **HIFO** (highest cost basis first) to minimise realised gains. Short-term vs long-term status (> 365 days) is tracked per lot.
- **Slippage:** configurable in basis points per ticker (default: 2 bps).
- **Benchmark:** QQQ buy-and-hold over the same period.

Metrics computed: CAGR, max drawdown, Sharpe ratio, Sortino ratio, Calmar ratio, win rate, total tax drag.

---

## Architecture

```
streamlit_app.py          ← Streamlit Cloud entry point
pages/                    ← Streamlit multipage navigation
  2_🎯_Signals.py
  3_📈_Regime.py
  4_🧪_Backtest.py
tradeagent/
  config.py               ← Pydantic config + YAML loader
  secrets.py              ← st.secrets / session_state / env resolution
  data/                   ← API clients (yfinance, Tiingo, FRED)
  analysis/
    technical.py          ← Indicators + per-ticker composite score [-1, 1]
    regime.py             ← 5-state classifier (pure function)
    sentiment.py          ← OpenAI news scorer (BYOK, session-cached)
  strategy/
    allocation.py         ← Regime → bucket weights (pure function)
    signals.py            ← Weights → BUY/SELL/HOLD signals (pure function)
    safety.py             ← Safety throttles (pure function)
    tax.py                ← HIFO/FIFO lot selection + wash-sale advisory
  backtest/
    engine.py             ← Walk-forward simulator (no lookahead)
    metrics.py            ← CAGR, drawdown, Sharpe, Sortino, Calmar
  ui/
    sidebar.py            ← Profile selector, BYOK key input, cost counter
    freshness.py          ← Data freshness banner (GitHub Actions timestamp)
    pages/dashboard.py    ← Dashboard logic imported by streamlit_app.py
data/                     ← Committed Parquet files (static historical data)
config/
  strategy_params.yaml    ← All thresholds and weights (tunable without code)
  universe.yaml           ← Tickers
  profiles/               ← conservative / moderate / aggressive allocations
scripts/
  refresh_static_data.py  ← Run by GitHub Actions; commits data/ updates
```

**Key architectural rule:** `analysis/`, `strategy/`, and `backtest/` are **pure functions** — no I/O, no Streamlit, no side effects. The Streamlit UI layer loads data and calls them. The backtest engine calls the exact same functions. This means what you see in the UI is exactly what the backtest replays.

---

## Bring-your-own OpenAI key

Sentiment scoring uses OpenAI to turn news headlines into structured scores (`score`, `confidence`, `themes`). The owner's key is never stored — visitors paste their own key in the sidebar.

- Key lives in `st.session_state` for the duration of the browser session only.
- A live cost counter shows estimated spend (token counts × per-model pricing).
- Without a key, sentiment is excluded from the regime composite (the UI notes this).
- Default model: `gpt-4o-mini`; opt-in to `gpt-4o` in the sidebar.
- Sentiment outputs are cached in `st.session_state.sentiment_cache` by article hash — re-scoring the same article never re-spends the budget.

---

## Data freshness

The app's worldview is always **"as of the last successful GitHub Actions run."** It never fetches live data at request time — it reads from the committed `data/` directory only.

A scheduled workflow runs **weekdays at 06:00 UTC** (pre-US-premarket), pulls the latest daily bars, macro series, and news, then commits any changes back to `main`. That commit triggers a Streamlit Cloud redeploy.

| When you visit | Data as of |
|---|---|
| Any weekday | Prior trading day's close |
| Weekend | Friday's close |
| After a US holiday | Prior trading day |
| During a GitHub Actions outage | Last successful workflow run |

The freshness banner on every page makes this explicit. If data is more than 2 US trading days stale, the banner turns yellow.

---

## Getting started (local dev)

```bash
git clone <repo>
cd trading-agent-compass
python -m venv .venv && source .venv/bin/activate
pip install -e .[dev]

# Copy example secrets and fill in values
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# Edit: set APP_PASSWORD, TIINGO_API_KEY, FRED_API_KEY

# Populate static data (prices, fundamentals, macro, news)
python scripts/refresh_static_data.py

# Run the app
streamlit run streamlit_app.py
```

---

## Deployment (Streamlit Community Cloud)

1. Push to a **private GitHub repo** named `trading-agent-compass`.
2. Add GitHub repo Secrets (Settings → Secrets → Actions):
   - `TIINGO_API_KEY`
   - `FRED_API_KEY`
3. Sign in to [share.streamlit.io](https://share.streamlit.io) → "New app" → select repo + `streamlit_app.py` → Deploy.
   Authorize the Streamlit GitHub App to access this specific private repo when prompted.
4. In Streamlit Cloud's "Secrets" panel, add:
   ```toml
   APP_PASSWORD = "..."
   TIINGO_API_KEY = "..."
   FRED_API_KEY = "..."
   GITHUB_TOKEN = "..."   # fine-grained PAT — see below
   ```
5. Manually trigger `Refresh static data` from the Actions tab. Confirm it runs green.
6. Visit the URL, enter the password, confirm the QQQ chart loads.

**GitHub PAT for freshness banner:** Fine-grained token, scoped to this repo only, with **Actions: Read-only** permission. Create at GitHub → Settings → Developer Settings → Personal access tokens → Fine-grained tokens. Set maximum expiry; when it expires the banner shows "?" and the app keeps working.

---

## Secrets reference

| Secret | Where set | Used by |
|---|---|---|
| `APP_PASSWORD` | Streamlit Cloud + local `secrets.toml` | Password gate |
| `TIINGO_API_KEY` | Streamlit Cloud + GitHub Actions + local | News ingestion |
| `FRED_API_KEY` | Streamlit Cloud + GitHub Actions + local | Macro data (DGS10, DGS2) |
| `GITHUB_TOKEN` | Streamlit Cloud + local | Freshness banner timestamp |
| `OPENAI_API_KEY` | **Never set by owner** | Visitors paste their own in the sidebar |

---

## Make targets

```bash
make install       # pip install -e .[dev]
make dev           # streamlit run streamlit_app.py
make test          # pytest
make lint          # ruff check
make fmt           # ruff format + black
make typecheck     # mypy tradeagent
make refresh-data  # python scripts/refresh_static_data.py
make clean         # remove __pycache__, build artifacts
```

---

## CLI (local dev only)

```bash
tradectl config validate          # validate all config files
tradectl refresh prices --ticker QQQ --since 2024-01-01
tradectl refresh all --since 2010-01-01
tradectl status                   # show data date and row counts
```

---

## Disclaimers

- **Advisory only.** This system never places orders.
- **Not financial advice.** Use your own judgment.
- **Leveraged ETFs are dangerous.** TQQQ/SQQQ can lose over 90% in a severe bear market. Understand what you hold before acting on any recommendation.
- **No guarantees.** Backtested performance does not predict future results.
