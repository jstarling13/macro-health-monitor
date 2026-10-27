"""Data sources. Everything here is free and needs no API key.

FRED is read through its public CSV download (fredgraph.csv) rather than the
JSON API. That endpoint has no key, no rate limit we have hit, and returns the
full history in one request -- this is the fix for the empty/partial pulls the
API gave on long dollar-index histories.

Every download is cached in data/cache/. If a download fails, the cached copy
is used and the result is marked stale, so the dashboard keeps working during
an outage instead of plotting nothing.
"""
from __future__ import annotations

import io
import os
import time
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import requests

CACHE = Path(__file__).resolve().parent.parent / "data" / "cache"
CACHE.mkdir(parents=True, exist_ok=True)
FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"
SHILLER_URLS = [
    "https://img1.wsimg.com/blobby/go/e5e77e0b-59d1-44d9-ab25-4763ac982e53/downloads/ie_data.xls",
    "http://www.econ.yale.edu/~shiller/data/ie_data.xls",
]
# How old a cached download may be before it is fetched again. The daily
# cloud build sets this to 0: restored caches look brand-new to the file
# system, so without it the hosted site would never re-download.
MAX_AGE_HOURS = float(os.environ.get("MHD_MAX_AGE_HOURS", 12))


@dataclass
class FetchLog:
    """What happened on each download, shown on the Data page."""
    rows: list

    def add(self, sid, status, last_obs, n):
        self.rows.append({"series": sid, "status": status, "last_obs": last_obs, "rows": n})


LOG = FetchLog(rows=[])


def _fresh(path: Path) -> bool:
    return path.exists() and (time.time() - path.stat().st_mtime) < MAX_AGE_HOURS * 3600


def _get(url: str, tries: int = 3) -> bytes:
    err = None
    for i in range(tries):
        try:
            # FRED's CSV endpoint stalls (read timeout) for browser-style and
            # custom User-Agents but answers instantly for curl's. Tested
            # 2026-10-27; likely the cause of the old "empty pull" failures.
            r = requests.get(url, timeout=30, headers={"User-Agent": "curl/8.7.1"})
            r.raise_for_status()
            return r.content
        except Exception as e:  # network errors, 5xx
            err = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"download failed: {url}: {err}")


def _parse_fred(raw: bytes, sid: str) -> pd.Series:
    df = pd.read_csv(io.BytesIO(raw))
    if df.shape[1] < 2 or df.empty:
        raise ValueError(f"FRED {sid}: empty or malformed CSV")
    s = pd.to_numeric(df.iloc[:, 1], errors="coerce")  # "." means missing
    s.index = pd.to_datetime(df.iloc[:, 0])
    s = s.dropna()
    if s.empty:
        raise ValueError(f"FRED {sid}: no numeric values")
    s.name = sid
    return s


def fred(sid: str, offline: bool = False) -> pd.Series:
    """Full history of one FRED series, indexed by FRED's observation date."""
    path = CACHE / f"{sid}.csv"
    if not offline and not _fresh(path):
        try:
            raw = _get(FRED_CSV.format(sid=sid))
            s = _parse_fred(raw, sid)  # validate before overwriting cache
            path.write_bytes(raw)
            LOG.add(sid, "live", s.index[-1].date(), len(s))
            return s
        except Exception as e:
            if not path.exists():
                raise
            LOG.add(sid, f"STALE cache ({type(e).__name__})", None, None)
    s = _parse_fred(path.read_bytes(), sid)
    if not LOG.rows or LOG.rows[-1]["series"] != sid:
        LOG.add(sid, "cache", s.index[-1].date(), len(s))
    return s


def shiller(offline: bool = False) -> pd.DataFrame:
    """Shiller monthly S&P data: P (monthly average price), D, E (12m trailing),
    indexed by month-end. Used for long price/dividend history."""
    path = CACHE / "ie_data.xls"
    if not offline and not _fresh(path):
        for url in SHILLER_URLS:
            try:
                raw = _get(url)
                tmp = CACHE / "ie_data.tmp"
                tmp.write_bytes(raw)
                df = _parse_shiller(tmp)
                tmp.replace(path)
                LOG.add("SHILLER", "live", df.index[-1].date(), len(df))
                return df
            except Exception:
                continue
        if not path.exists():
            raise RuntimeError("Shiller data unavailable and no cache")
        LOG.add("SHILLER", "STALE cache", None, None)
    df = _parse_shiller(path)
    LOG.add("SHILLER", "cache", df.index[-1].date(), len(df))
    return df


def _parse_shiller(path: Path) -> pd.DataFrame:
    d = pd.read_excel(path, sheet_name="Data", header=None, skiprows=8, usecols=range(5))
    d.columns = ["date", "P", "D", "E", "CPI"]
    d["date"] = pd.to_numeric(d["date"], errors="coerce")
    d = d.dropna(subset=["date", "P"])
    # 1871.1 means October (the float drops the trailing zero of "1871.10").
    yr = d["date"].astype(int)
    mo = ((d["date"] - yr) * 100).round().astype(int)
    d.index = pd.to_datetime(dict(year=yr, month=mo, day=1)) + pd.offsets.MonthEnd(0)
    out = d[["P", "D", "E"]].apply(pd.to_numeric, errors="coerce")
    if len(out) < 1000:
        raise ValueError("Shiller file looks truncated")
    return out


def user_eps(path: Path | None = None) -> pd.Series | None:
    """Optional S&P 500 EPS export (FactSet / LSEG). CSV with columns
    `date,eps` (quarter-end date, 4-quarter trailing or quarterly EPS) and an
    optional `release_date`. Returns None when the file is absent."""
    path = path or (CACHE.parent / "sp500_eps.csv")
    if not path.exists():
        return None
    df = pd.read_csv(path, parse_dates=["date"])
    s = df.set_index("date")["eps"].astype(float).sort_index()
    s.name = "user_eps"
    return s
