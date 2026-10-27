"""Publish gate. Every build runs these checks before anything is written.

ERROR   -> the build stops: data.json and the gauge log are NOT updated, the
           cloud job fails (so the live site keeps the last good version) and
           an alert issue is opened.
WARNING -> the build publishes, and the warning is shown on the site.

A deliberate override exists for one case only: a large day-over-day move in
the gauge (set MHD_ALLOW_BIG_MOVE=1 after confirming the move is real).
"""
from __future__ import annotations

import math
import os
from datetime import datetime, timezone

import pandas as pd

# Maximum age (days) of the newest observation, by FRED frequency.
MAX_AGE_DAYS = {"daily": 10, "weekly": 21, "monthly": 75, "quarterly": 200}
EXEMPT = {"TWEXBMTH", "SHILLER"}     # discontinued / historical-only by design
BIG_MOVE = 15.0                      # gauge points vs the previous run
BIG_FACTOR_MOVE = 50.0               # factor points vs the previous run


def _num(x) -> bool:
    return isinstance(x, (int, float)) and not (isinstance(x, float) and (math.isnan(x) or math.isinf(x)))


def _freq_key(freq: str | None) -> str | None:
    f = (freq or "").lower()
    for k in MAX_AGE_DAYS:
        if f.startswith(k):
            return k
    return None


def run(payload: dict, prev: dict | None = None, today: datetime | None = None) -> dict:
    today = (today or datetime.now(timezone.utc)).replace(tzinfo=None)
    errors, warnings, passed = [], [], []

    def check(ok: bool, msg: str, level: str = "error"):
        if ok:
            passed.append(msg)
        else:
            (errors if level == "error" else warnings).append(msg)

    hd = payload.get("headline", {})
    check(_num(hd.get("score")) and 0 <= hd["score"] <= 100, f"Headline gauge is a number in 0-100 (got {hd.get('score')})")

    fs = payload.get("factors", [])
    check(len(fs) == 6, f"All six factors present (got {len(fs)})")
    for f in fs:
        check(_num(f.get("score")) and 0 <= f["score"] <= 100, f"{f.get('label')} score in 0-100 (got {f.get('score')})")
        for p in f.get("parts", []):
            check(_num(p.get("value")), f"{f.get('label')}: {p.get('label')} has a value", "warning")

    H = payload.get("history", {})
    n = len(H.get("dates", []))
    check(n >= 560, f"Gauge history has at least 560 months (got {n})")
    for k, vals in (H.get("factors") or {}).items():
        check(len(vals) == n, f"{k} history length matches ({len(vals)} vs {n})")
    if n:
        last = pd.Timestamp(H["dates"][-1] + "-01")
        check((today - last).days <= 62, f"History reaches the current month (last {H['dates'][-1]})")
        recent = [x for x in H["health"][-24:] if _num(x)]
        check(len(recent) == 24, "No gaps in the last 24 months of the gauge")
    spx = [x for x in H.get("spx", [])[-24:] if _num(x)]
    check(len(spx) == 24 and all(x > 0 for x in spx), "S&P 500 prices present and positive for the last 24 months")

    for m in payload.get("markets", []):
        age = (today - pd.Timestamp(m["as_of"])).days
        check(age <= MAX_AGE_DAYS["daily"], f"{m['label']} is current (last {m['as_of']}, {age} days old)", "warning")
        if m["kind"] == "rate":
            check(-10 < m["last"] < 40, f"{m['label']} in a sane range ({m['last']})")
        else:
            check(m["last"] > 0, f"{m['label']} is positive ({m['last']})")
        d1 = m.get("chg_1d")
        if _num(d1):
            limit = 200 if m["kind"] == "rate" else (60 if m["id"] in {"VIXCLS", "DCOILWTICO"} else 15)
            check(abs(d1) <= limit, f"{m['label']} one-day move looks plausible ({d1:+.1f})", "warning")

    used = {p["series"] for f in fs for p in f.get("parts", [])}
    cites = {s["id"]: s for s in payload.get("sources", [])}
    check(used <= set(cites), f"Every series used is cited (missing: {sorted(used - set(cites))})")
    for sid, s in cites.items():
        check(bool(s.get("title")), f"{sid} has a title on the Sources page", "warning")
        status = str(s.get("fetch_status") or "")
        check(not status.startswith(("STALE", "REJECTED")), f"{sid} downloaded cleanly ({status or 'n/a'})", "warning")
        fk = _freq_key(s.get("frequency"))
        if sid in EXEMPT or not fk or not s.get("last_obs"):
            continue
        obs = pd.Timestamp(s["last_obs"])
        if fk == "quarterly":
            obs = obs + pd.DateOffset(months=3)       # FRED dates a quarter by its first day
        elif fk == "monthly":
            obs = obs + pd.DateOffset(months=1)
        age = (today - obs).days
        lvl = "error" if (sid in used and age > 2 * MAX_AGE_DAYS[fk]) else "warning"
        check(age <= MAX_AGE_DAYS[fk], f"{sid} is up to date (latest observation {s['last_obs']}, period ended {age} days ago)", lvl)

    B = payload.get("backtest", {})
    check(B.get("months", 0) >= 550, f"Backtest covers at least 550 months (got {B.get('months')})")
    for r in B.get("perf", []):
        if r.get("name") != "T-bills":
            check(_num(r.get("CAGR")) and -0.3 < r["CAGR"] < 0.4, f"{r.get('name')} CAGR is plausible ({r.get('CAGR')})")

    allow = os.environ.get("MHD_ALLOW_BIG_MOVE") == "1"
    if prev and _num(prev.get("health")) and _num(hd.get("score")):
        move = hd["score"] - prev["health"]
        check(abs(move) <= BIG_MOVE or allow,
              f"Gauge moved {move:+.1f} points since {prev.get('date')} (limit {BIG_MOVE:.0f}; "
              "confirm the move is real, then re-run with MHD_ALLOW_BIG_MOVE=1)")
        for f in fs:
            pv = prev.get(f["key"])
            if _num(pv) and _num(f.get("score")):
                check(abs(f["score"] - pv) <= BIG_FACTOR_MOVE, f"{f['label']} moved {f['score'] - pv:+.0f} points since {prev.get('date')}", "warning")

    return {"ok": not errors, "errors": errors, "warnings": warnings, "passed": len(passed),
            "checked_at": today.strftime("%Y-%m-%dT%H:%MZ")}
