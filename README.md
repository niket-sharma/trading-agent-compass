# Trading Agent Compass

**Author:** Niket Sharma (sharma.niket@gmail.com)

Personal advisory-only trading assistant. Regime-based signals for QQQ / QLD / TQQQ / SQQQ and a handful of single names.

**Advisory only — this system never places orders.**

---

## Live App

> URL: _(placeholder — update after Streamlit Cloud deploy)_
>
> Access: password-gated. Contact the owner for the password.

---

## How fresh is the data?

The app's worldview is always "as of the last successful GitHub Actions run."
A scheduled workflow runs **weekdays at 06:00 UTC** (pre-US-premarket), pulls
the latest daily bars and news, and commits any changes back to `main`. That commit
triggers a Streamlit Cloud redeploy with fresh data.

| When you visit | Data freshness |
|---|---|
| Any time on a weekday | As of prior trading day's close |
| Weekend | As of Friday's close |
| Morning after a US holiday | As of the previous trading day |
| During a GitHub Actions outage | As of whenever the workflow last succeeded |

The freshness banner on every page makes this explicit. If data is more than
2 trading days stale, the banner turns yellow.

---

## Getting started (local dev)

```bash
git clone <repo>
cd trading-agent-compass
python -m venv .venv && source .venv/bin/activate
pip install -e .[dev]

# Copy example secrets, fill in values
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# Edit .streamlit/secrets.toml: set APP_PASSWORD, TIINGO_API_KEY, FRED_API_KEY

# Populate static data (prices, fundamentals, macro, news)
python scripts/refresh_static_data.py

# Run the app
streamlit run streamlit_app.py
```

---

## How to refresh static data

**Automatic:** GitHub Actions runs the refresh workflow weekdays at 06:00 UTC.
You can also trigger it manually from the Actions tab in the GitHub UI.

**Manual (local):**
```bash
python scripts/refresh_static_data.py
```
Equivalent to `tradectl refresh all --since 2010-01-01`.

After a manual run, commit the updated `data/` directory:
```bash
git add data/
git commit -m "chore: refresh static data $(date -u +%Y-%m-%d)"
git push
```

---

## How to deploy (Streamlit Community Cloud)

1. Push the repo to GitHub as a **private repo** named `trading-agent-compass`.
2. Configure GitHub repo Secrets (Settings → Secrets → Actions):
   - `TIINGO_API_KEY`
   - `FRED_API_KEY`
3. Sign in to [Streamlit Community Cloud](https://streamlit.io/cloud).
4. "New app" → point to the repo + `streamlit_app.py` → deploy.
   When prompted, authorize the Streamlit GitHub App to access this specific private repo.
   Free tier supports private repos.
5. In Streamlit Cloud's "Secrets" panel, paste (TOML format):
   ```toml
   APP_PASSWORD = "..."       # owner-chosen; share out-of-band with invited users
   TIINGO_API_KEY = "..."
   FRED_API_KEY = "..."
   # GITHUB_TOKEN added in Phase 1 for the freshness banner timestamp
   ```
6. Manually trigger the `Refresh static data` workflow from the Actions tab.
   Confirm it runs green and either commits or reports "No data changes".
7. Visit the Streamlit Cloud URL, enter the password, confirm the QQQ chart loads.

---

## Freshness banner — Phase 1 timestamp

The banner shows "Last refresh: ?" in Phase 0 (data date only — no auth needed).
Phase 1 adds an authenticated GitHub API call that fills in the real timestamp.

**PAT setup (Phase 1):**
1. GitHub Settings → Developer Settings → Personal access tokens → Fine-grained tokens
2. Resource owner: your GitHub account
3. Repository access: select `trading-agent-compass` only
4. Permissions → Repository → **Actions: Read-only** (nothing else)
5. Expiry: maximum allowed (currently 1 year — set a calendar reminder to rotate)
6. Add to Streamlit Cloud secrets: `GITHUB_TOKEN = "<PAT value>"`
7. Also add to local `.streamlit/secrets.toml` for dev parity

When the PAT expires, the banner reverts to "?" — the app keeps working.

---

## How to run CLI commands

```bash
# Validate all config files
tradectl config validate

# Refresh just prices for one ticker
tradectl refresh prices --ticker QQQ --since 2024-01-01

# Refresh everything
tradectl refresh all --since 2010-01-01

# Show data status
tradectl status
```

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

## Secrets configuration

| Secret | Where set | Used by |
|---|---|---|
| `APP_PASSWORD` | Streamlit Cloud + local secrets.toml | Password gate |
| `TIINGO_API_KEY` | Streamlit Cloud + GitHub Actions + local | News ingestion |
| `FRED_API_KEY` | Streamlit Cloud + GitHub Actions + local | Macro data |
| `GITHUB_TOKEN` | Streamlit Cloud + local (Phase 1) | Freshness banner timestamp |
| `OPENAI_API_KEY` | **Never set by owner** | Visitors paste their own in the sidebar |

---

## Disclaimers

- **Advisory only.** This system never places orders.
- **Not financial advice.** Use your own judgment.
- **Leveraged ETFs are dangerous.** TQQQ/SQQQ can lose >90% in a severe bear market.
  Understand what you're holding before following any recommendation.
- **No guarantees.** Backtested performance does not predict future results.

---

## Project phases

| Phase | Status | Description |
|---|---|---|
| 0 | ✅ In progress | Foundations, data pipeline, deploy |
| 1 | Planned | Analysis: technical, sentiment, regime |
| 2 | Planned | Backtest engine |
| 3 | Planned | Strategy: signals, allocation, tax |
| 4 | Planned | Polish and share |
| 5 | Planned | 3-6 months live use + validation |

See `plan.md` for full detail.
