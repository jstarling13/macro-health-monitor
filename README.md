# Macro Health Monitor

A daily macro dashboard: a six-factor Health Gauge (GDP, Fed policy, inflation, corporate earnings, the U.S. dollar, credit & liquidity), a daily markets monitor, and a point-in-time backtest.

- **Site:** `site/` is a static web app (HTML/CSS/JS + ECharts). Every chart has a **Data** table and **CSV** export, and every card cites its sources.
- **Sources page:** each series' title, publisher, release, units and update time are read from FRED at refresh time.
- **Model:** `mhd/` (Python). `mhd.export` writes `site/data.json`; the site only reads that file.
- **Streamlit app** (`app.py`): the older internal view, kept for quick experiments.

## Daily use
```
./scripts/daily_refresh.sh                                   # pull data, rebuild data.json, append gauge log
.venv/bin/python -m http.server 8841 --directory site        # view at http://localhost:8841
```
The hosted site rebuilds itself on GitHub Actions (`.github/workflows/daily.yml`) every morning and every weekday evening, and can be run on demand from the Actions tab.
The log lives in `logs/refresh.log`; the daily gauge history is in `data/history/gauge_log.csv`.

## Setup and tests
```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q
```
No API keys. FRED's CSV endpoint stalls for browser-style User-Agents, so `mhd/sources.py` sends curl's.

## Data notes
- Earnings use BEA corporate profits (all U.S. companies). To use S&P 500 EPS instead, save `data/sp500_eps.csv` (`date,eps`).
- Shiller's file supplies S&P prices and dividends to mid-2024; later prices come from FRED SP500, and dividends are estimated at the last yield.
- History uses today's revised GDP and profit figures, not first prints.

## Safety controls
| Risk | Control | Where |
|---|---|---|
| Bad or partial data gets published | Publish gate: 120+ checks (scores 0–100, no recent gaps, history length, prices positive, rates in range, every series cited, inputs up to date). A failed hard check stops the build: `data.json` and the gauge log are not touched, and the live site keeps its last good version. | `mhd/validate.py`, `mhd/export.py` |
| A real-looking but wrong jump | Gauge moving more than 15 points since the previous refresh is blocked until a person confirms it | `MHD_ALLOW_BIG_MOVE=1` locally, or the "allow big move" box on **Actions → Daily rebuild → Run workflow** |
| FRED returns a truncated series | Download guard rejects any response with fewer rows, a later start or an earlier end than the saved copy; the saved copy is used and flagged REJECTED | `mhd/sources.py` (`_shrunk`) |
| FRED is down | Last good download is used and flagged STALE on the Sources page | `mhd/sources.py` |
| The daily job silently stops | Site shows a "Stale data" banner when the build is more than 3 days old; a failed scheduled run opens a GitHub issue | `site/app.js` (`banner`), workflow |
| A library update breaks the math | Exact versions pinned for the cloud build | `requirements-ci.txt` |
| Half-written files | `data.json` is written to a temp file and swapped in atomically | `mhd/export.py` |
| Code changes break things | 23 tests run before and after each build, including tests that break data on purpose | `tests/` |

### If the build fails
1. Open the alert issue (or **Actions → Daily rebuild**) and read the failed check.
2. A **rejected-build** file is attached to the failed run for inspection.
3. If FRED is the cause, do nothing: the next scheduled run retries.
4. If the gauge really moved more than 15 points (for example after a big GDP revision), check the factor that moved, then **Run workflow** with "allow big move" ticked.
5. Close the issue once a run succeeds.

GitHub pauses scheduled workflows in public repos after 60 days with no repository activity. The daily gauge-log commit counts as activity, but if the stale banner ever appears, re-enable the workflow under **Actions**.
