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
