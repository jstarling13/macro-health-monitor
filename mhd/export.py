"""Write site/data.json: everything the web dashboard shows, computed in Python.

Run:  .venv/bin/python -m mhd.export          (live data)
      .venv/bin/python -m mhd.export --offline (cached data only)
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import sys

from . import backtest, meta, model, sources, validate

SITE = Path(__file__).resolve().parent.parent / "site"

# How to show each component in natural terms (the model stores signed values
# where higher = better; the site shows the actual reading).
DISPLAY = {
    "gdp_growth":      ("Real GDP growth (annualized)", "%", 1, "A191RL1Q225SBEA"),
    "ff_change_6m":    ("Fed funds change, 6 months", "pp", -1, "FEDFUNDS"),
    "real_ff":         ("Real fed funds rate", "%", -1, "FEDFUNDS"),
    "core_cpi_gap":    ("Core CPI, year over year", "%", None, "CPILFESL"),
    "profits_yoy":     ("Corporate profits, year over year", "%", 1, "CP"),
    "usd_6m":          ("Broad dollar, 6-month change", "%", -1, "DTWEXBGS"),
    "sloos":           ("Banks tightening C&I standards (net)", "%", -1, "DRTSCILM"),
    "bank_credit_yoy": ("Bank credit, year over year", "%", 1, "TOTBKCR"),
    "m2_yoy":          ("M2 money supply, year over year", "%", 1, "M2SL"),
}
BETTER = {
    "gdp_growth": "Higher is better", "ff_change_6m": "Cuts score higher",
    "real_ff": "Lower scores higher", "core_cpi_gap": "Closer to 2% scores higher",
    "profits_yoy": "Higher is better", "usd_6m": "A weaker dollar scores higher",
    "sloos": "Less tightening scores higher", "bank_credit_yoy": "Higher is better",
    "m2_yoy": "Higher is better",
}


def _clean(x):
    """JSON-safe: NaN -> None, numpy -> python, round floats."""
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    if isinstance(x, (np.floating, float)):
        return None if (x is None or math.isnan(x) or math.isinf(x)) else round(float(x), 4)
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (np.bool_,)):
        return bool(x)
    if isinstance(x, (pd.Timestamp, datetime, date)):
        return x.strftime("%Y-%m-%d")
    return x


def _records(df: pd.DataFrame) -> list[dict]:
    return [_clean(r) for r in df.reset_index().to_dict(orient="records")]


# Daily market monitor. kind: "rate" -> changes in basis points; "level" -> %.
# Reporting frequency used for date labels on the site.
FREQ = {"A191RL1Q225SBEA": "quarterly", "CP": "quarterly", "DRTSCILM": "quarterly",
        "TOTBKCR": "weekly", "DTWEXBGS": "daily"}

DAILY = [
    ("SP500", "S&P 500", "level", "index"),
    ("NASDAQCOM", "Nasdaq Composite", "level", "index"),
    ("VIXCLS", "VIX volatility index", "level", "index"),
    ("DTWEXBGS", "Broad U.S. dollar index", "level", "index"),
    ("DGS2", "2-year Treasury yield", "rate", "%"),
    ("DGS10", "10-year Treasury yield", "rate", "%"),
    ("T10Y2Y", "10-year minus 2-year spread", "rate", "pp"),
    ("DFF", "Effective fed funds rate", "rate", "%"),
    ("T10YIE", "10-year breakeven inflation", "rate", "%"),
    ("BAMLH0A0HYM2", "High-yield credit spread", "rate", "pp"),
    ("DCOILWTICO", "WTI crude oil", "level", "$/bbl"),
]
LOG_PATH = Path(__file__).resolve().parent.parent / "data" / "history" / "gauge_log.csv"


def _change(s: pd.Series, days: int, kind: str):
    s = s.dropna()
    if len(s) < 2:
        return None
    ref = s[s.index <= s.index[-1] - pd.Timedelta(days=days)]
    if ref.empty:
        return None
    a, b = ref.iloc[-1], s.iloc[-1]
    return (b - a) * 100 if kind == "rate" else (b / a - 1) * 100


def daily_markets(offline: bool) -> list[dict]:
    out = []
    for sid, label, kind, unit in DAILY:
        s = sources.fred(sid, offline).dropna()
        ytd_ref = s[s.index < pd.Timestamp(s.index[-1].year, 1, 1)]
        tail = s[s.index >= s.index[-1] - pd.DateOffset(years=5)]
        out.append({
            "id": sid, "label": label, "kind": kind, "unit": unit,
            "last": s.iloc[-1], "as_of": s.index[-1],
            "chg_1d": (s.iloc[-1] - s.iloc[-2]) * 100 if kind == "rate" else (s.iloc[-1] / s.iloc[-2] - 1) * 100,
            "chg_1w": _change(s, 7, kind), "chg_1m": _change(s, 30, kind),
            "chg_1y": _change(s, 365, kind),
            "chg_ytd": (None if ytd_ref.empty else ((s.iloc[-1] - ytd_ref.iloc[-1]) * 100 if kind == "rate"
                        else (s.iloc[-1] / ytd_ref.iloc[-1] - 1) * 100)),
            "pct_rank_5y": float((tail < s.iloc[-1]).mean() * 100),
            "dates": [d.strftime("%Y-%m-%d") for d in tail.index], "values": tail.tolist(),
        })
    return out


def previous_run(today: str) -> dict | None:
    """Most recent gauge-log row from an earlier day."""
    if not LOG_PATH.exists():
        return None
    df = pd.read_csv(LOG_PATH)
    df = df[df["date"] < today]
    return None if df.empty else df.iloc[-1].to_dict()


def append_log(payload: dict) -> pd.DataFrame:
    """One row per run-day: the gauge as published that day. Builds the
    day-over-day record that a daily tool needs."""
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    row = {"date": datetime.now().strftime("%Y-%m-%d"), "health": payload["headline"]["score"]}
    row.update({f["key"]: f["score"] for f in payload["factors"]})
    df = pd.read_csv(LOG_PATH) if LOG_PATH.exists() else pd.DataFrame(columns=list(row))
    df = df[df["date"] != row["date"]]
    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True).sort_values("date")
    df.to_csv(LOG_PATH, index=False, float_format="%.2f")
    return df


def build_payload(offline: bool = False, threshold: float = 45.0) -> dict:
    sources.LOG.rows.clear()
    m = model.build(offline=offline)
    raw, L = m.raw, m.latest
    start = m.factors.dropna().index[0]

    core = raw["CPILFESL"]
    core_yoy = (core.pct_change(12, fill_method=None) * 100).dropna()

    factors = []
    for f in model.FACTORS:
        parts = []
        for c in f.components:
            label, unit, sign, sid = DISPLAY[c.key]
            p = L[f.key]["parts"][c.key]
            if c.key == "core_cpi_gap":
                val = float(core_yoy.iloc[-1])
            else:
                val = p["value"] * sign if p["value"] is not None else None
            obs = raw[sid].dropna().index[-1]
            parts.append({"key": c.key, "label": label, "unit": unit, "value": val,
                          "score": p["score"], "series": sid, "as_of": obs,
                          "frequency": FREQ.get(sid, "monthly"),
                          "direction": BETTER[c.key]})
        hist = m.factors[f.key].loc[start:]
        fg, fw = model.grade(L[f.key]["score"])
        factors.append({"key": f.key, "label": f.label, "why": f.why, "score": L[f.key]["score"],
                        "grade": fg, "word": fw, "parts": parts,
                        "change_3m": hist.iloc[-1] - hist.iloc[-4] if len(hist) > 4 else None})

    core_m = core.groupby(core.index.to_period("M")).last()
    core_m.index = core_m.index.to_timestamp()
    core_pit = model._known_at((core_m.pct_change(12, fill_method=None) * 100).dropna(), 1, m.comps.index)
    comp_hist = {}
    for f in model.FACTORS:
        for c in f.components:
            sign = DISPLAY[c.key][2]
            v = core_pit if c.key == "core_cpi_gap" else m.comps[c.key] * sign
            comp_hist[c.key] = {"value": v.loc[start:].tolist(),
                                "score": model.expanding_percentile(m.comps[c.key]).loc[start:].tolist()}

    h = m.health.loc[start:]
    hg, hw = model.grade(L["_health"])
    price = m.market["price"].reindex(h.index)
    rec = raw["USREC"].copy()
    rec.index = rec.index + pd.offsets.MonthEnd(0)
    rec = rec.reindex(h.index).fillna(0)

    bt = backtest.summary(h, m.market, threshold)
    s = bt["strategy"]
    eq_s, eq_b = (1 + s["strategy"]).cumprod(), (1 + s["stock"]).cumprod()
    fd = backtest.factor_diagnostics(m.factors.loc[start:], h, m.market)
    rb = backtest.robustness(h, m.market, threshold)

    # Threshold sweep so the page can show sensitivity without recomputing.
    sweep = []
    for t in range(25, 80, 5):
        st_ = backtest.strategy(h, m.market, t)
        pf = backtest.perf(st_["strategy"], st_["cash"])
        sweep.append({"threshold": t, "cagr": pf["CAGR"], "max_drawdown": pf["max_drawdown"],
                      "sharpe": pf["sharpe"], "pct_invested": st_["in_market"].mean()})

    payload = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
            "latest_data": None,  # filled below from the daily series
            "backtest_start": start,
            "dividends_estimated_after": m.market.attrs.get("dividends_estimated_after"),
            "price_splice": m.market.attrs.get("fred_splice_start"),
            "sources": sources.LOG.rows,
            "threshold": threshold,
        },
        "headline": {
            "score": L["_health"], "grade": hg, "word": hw,
            "pit_series_last": h.iloc[-1],
            # Changes compare the point-in-time gauge with itself. Comparing
            # today's newest-data reading with past point-in-time readings
            # mixed two bases (e.g. the dollar showed -22 when it rose +5).
            "change_1m": h.iloc[-1] - h.iloc[-2], "change_3m": h.iloc[-1] - h.iloc[-4],
            "change_12m": h.iloc[-1] - h.iloc[-13],
        },
        "factors": factors,
        "history": {
            "dates": [d.strftime("%Y-%m") for d in h.index],
            "health": h.tolist(),
            "factors": {f.key: m.factors[f.key].loc[start:].tolist() for f in model.FACTORS},
            "spx": price.tolist(),
            "spx_drawdown": (price / price.cummax() - 1).tolist(),
            "recession": rec.astype(int).tolist(),
            "components": comp_hist,
        },
        "markets": daily_markets(offline),
        "backtest": {
            "months": len(s),
            "stats": _records(bt["stats"].set_index("horizon")),
            "buckets_12m": _records(bt["buckets_12m"]),
            "perf": _records(bt["perf"].rename_axis("name")),
            "by_decade": _records(bt["by_decade"].set_index("decade")),
            "factor_diag": _records(fd.set_index("signal")),
            "equity": {"dates": [d.strftime("%Y-%m") for d in s.index],
                       "strategy": eq_s.tolist(), "buy_hold": eq_b.tolist(),
                       "dd_strategy": (eq_s / eq_s.cummax() - 1).tolist(),
                       "dd_buy_hold": (eq_b / eq_b.cummax() - 1).tolist(),
                       "in_market": s["in_market"].astype(int).tolist()},
            "switches_per_year": bt["switches_per_year"],
            "sweep": sweep,
            "robustness": {"table": _records(rb["table"].set_index("test")), "nonoverlap": rb["nonoverlap"],
                           "bootstrap_ci": rb["bootstrap_ci"]},
        },
    }
    ids = sorted({c.series for f in model.FACTORS for c in f.components} - {"USD_BROAD"}
                 | {"TWEXBMTH", "DTWEXBGS", "SP500", "TB3MS", "USREC"} | {d[0] for d in DAILY})
    md = meta.fred_meta(ids, offline)
    status = {r["series"]: r for r in sources.LOG.rows}
    used_in = {}
    for f in model.FACTORS:
        for c in f.components:
            for sid in (["TWEXBMTH", "DTWEXBGS"] if c.series == "USD_BROAD" else [c.series]):
                used_in.setdefault(sid, []).append(f"{f.label}: {DISPLAY[c.key][0]} (published-data lag {c.lag} mo)")
    for sid, why in {"SP500": "S&P 500 prices after the Shiller series ends; daily monitor",
                     "TB3MS": "Cash return in the backtest", "USREC": "Recession shading on charts"}.items():
        used_in.setdefault(sid, []).append(why)
    for sid, label, *_ in DAILY:
        used_in.setdefault(sid, []).append(f"Daily markets: {label}")
    cites = []
    for sid in ids:
        r = dict(md.get(sid, {"id": sid}))
        st_ = status.get(sid, {})
        r.update({"used_for": sorted(set(used_in.get(sid, []))), "fetch_status": st_.get("status"),
                  "last_obs": raw[sid].dropna().index[-1] if sid in raw else
                  sources.fred(sid, True).index[-1]})
        cites.append(r)
    sh = dict(meta.SHILLER)
    sh.update({"used_for": [f"S&P 500 monthly prices to {m.market.attrs['fred_splice_start'] - pd.offsets.MonthEnd(1):%b %Y} "
                            f"and dividends to {m.market.attrs['dividends_estimated_after']:%b %Y} (backtest returns)"],
               "fetch_status": status.get("SHILLER", {}).get("status"),
               "last_obs": sources.shiller(True)["P"].index[-1]})
    cites.append(sh)
    payload["sources"] = cites
    payload["meta"]["latest_data"] = max(mk["as_of"] for mk in payload["markets"])
    return _clean(payload)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    a = ap.parse_args()
    payload = build_payload(offline=a.offline)
    today = datetime.now().strftime("%Y-%m-%d")
    prev = previous_run(today)
    checks = validate.run(payload, prev)
    payload["checks"] = checks
    if prev:
        payload["headline"]["vs_prev_run"] = {"date": prev["date"], "change": payload["headline"]["score"] - prev["health"]}
    SITE.mkdir(exist_ok=True)
    if not checks["ok"]:
        # Keep the last good data.json and gauge log untouched.
        bad = SITE.parent / "data" / "rejected.json"
        bad.parent.mkdir(exist_ok=True)
        bad.write_text(json.dumps(_clean(payload), indent=1))
        print("PUBLISH BLOCKED. Failed checks:", *[f"  - {e}" for e in checks["errors"]], sep="\n")
        print(f"Rejected build saved to {bad}; site/data.json left unchanged.")
        sys.exit(1)
    log = append_log(payload)
    payload["gauge_log"] = _records(log.set_index("date"))
    out = SITE / "data.json"
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(_clean(payload), separators=(",", ":")))
    tmp.replace(out)  # atomic: a crash mid-write can't leave a half-written file
    print(f"wrote {out} ({out.stat().st_size/1024:.0f} KB); gauge {payload['headline']['score']:.1f} "
          f"{payload['headline']['grade']}; latest data {payload['meta']['latest_data']}; "
          f"checks: {checks['passed']} passed, {len(checks['warnings'])} warnings")
    for w in checks["warnings"]:
        print(f"  warning: {w}")


if __name__ == "__main__":
    main()
