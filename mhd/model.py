"""Six-factor macro health model.

Each factor is built from one or more components. Every component is signed so
that HIGHER = BETTER FOR STOCKS, then scored 0-100 as its percentile against
all history known at that date (expanding window, no look-ahead). A factor
score is the mean of its component scores; the Health Gauge is the weighted
mean of factor scores.

Point-in-time rule: a FRED observation dated d (FRED dates a period by its
first day) only enters the model at the month-end LAG months later, roughly
when it was first published. Lags are deliberately conservative.

Known limitation: FRED's CSV gives today's revised numbers, not what was first
printed. GDP and corporate profits get revised, so the backtest sees slightly
cleaner data than a live user did. Prices, the dollar, rates and the loan
officer survey are not revised.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import sources

MIN_HISTORY = 60  # months of history before a component is scored


@dataclass
class Component:
    key: str
    label: str
    series: str
    lag: int          # months after FRED observation date until known
    note: str = ""


@dataclass
class Factor:
    key: str
    label: str
    components: list[Component]
    why: str
    weight: float = 1.0


FACTORS: list[Factor] = [
    Factor("gdp", "GDP growth", [
        Component("gdp_growth", "Real GDP growth, % annualized", "A191RL1Q225SBEA", 4,
                  "Advance estimate ~1 month after quarter end; lag allows for delays."),
    ], "Faster real growth supports revenue and earnings."),
    Factor("fed", "Fed policy", [
        Component("ff_change_6m", "Fed funds, 6-month change (cuts score higher)", "FEDFUNDS", 0),
        Component("real_ff", "Real fed funds (fed funds minus core CPI; lower scores higher)", "FEDFUNDS", 1),
    ], "Rate cuts and low real rates loosen financial conditions."),
    Factor("inflation", "Inflation", [
        Component("core_cpi_gap", "Core CPI YoY distance from 2% (closer scores higher)", "CPILFESL", 1),
    ], "Inflation near 2% lets the Fed ease; far from it forces tightening."),
    Factor("earnings", "Corporate earnings", [
        Component("profits_yoy", "Corporate profits after tax, YoY %", "CP", 6,
                  "All U.S. corporations (BEA). Replaces hand-collected ticker data."),
    ], "Earnings growth is what ultimately drives prices."),
    Factor("usd", "U.S. dollar", [
        Component("usd_6m", "Broad dollar index, 6-month % change (weaker scores higher)", "USD_BROAD", 1,
                  "FRED broad trade-weighted index; 1973-2005 from the discontinued TWEXBMTH."),
    ], "A weaker dollar helps exports, foreign earnings and capital inflows."),
    Factor("credit", "Credit & liquidity", [
        Component("sloos", "Banks tightening C&I lending standards, net % (less tightening scores higher)",
                  "DRTSCILM", 2, "Fed Senior Loan Officer Survey, quarterly."),
        Component("bank_credit_yoy", "Bank credit, YoY %", "TOTBKCR", 1),
        Component("m2_yoy", "M2 money supply, YoY %", "M2SL", 1),
    ], "Fed lending and capital rules show up as how freely banks lend and how fast money supply grows."),
]

GRADES = [(70, "A", "Strong"), (60, "B", "Healthy"), (45, "C", "Neutral"),
          (35, "D", "Weak"), (0, "F", "Stressed")]


def grade(score: float) -> tuple[str, str]:
    if score is None or np.isnan(score):
        return "–", "No data"
    for cut, g, word in GRADES:
        if score >= cut:
            return g, word
    return "F", "Stressed"


# --------------------------------------------------------------------- data

def _monthly(s: pd.Series, how: str = "last") -> pd.Series:
    """Collapse to one value per period, dated at the period's first day so the
    lag arithmetic below matches FRED's own convention."""
    g = s.groupby(s.index.to_period("M"))
    out = g.mean() if how == "mean" else g.last()
    out.index = out.index.to_timestamp()
    return out


def _known_at(s: pd.Series, lag: int, grid: pd.DatetimeIndex) -> pd.Series:
    """Re-date observations to the month-end they became known, then carry the
    latest known value forward on the monthly grid."""
    if s.empty:
        return pd.Series(np.nan, index=grid)
    avail = (s.index + pd.DateOffset(months=lag)) + pd.offsets.MonthEnd(0)
    t = pd.Series(s.values, index=avail)
    t = t[~t.index.duplicated(keep="last")].sort_index()
    return t.reindex(grid.union(t.index)).ffill().reindex(grid)


def _quarterly_shift(s: pd.Series) -> pd.Series:
    """Move quarterly observations from quarter-start to quarter-end month."""
    out = s.copy()
    out.index = out.index + pd.DateOffset(months=2)
    return out


def load_raw(offline: bool = False) -> dict[str, pd.Series]:
    raw = {sid: sources.fred(sid, offline) for sid in
           ["A191RL1Q225SBEA", "FEDFUNDS", "CPILFESL", "CP", "DRTSCILM", "TOTBKCR",
            "M2SL", "TB3MS", "TWEXBMTH", "DTWEXBGS", "SP500", "USREC"]}
    raw["USD_BROAD"] = splice_dollar(raw["TWEXBMTH"], raw["DTWEXBGS"])
    return raw


def splice_dollar(old: pd.Series, new: pd.Series) -> pd.Series:
    """One monthly broad-dollar series from 1973. The two FRED indexes have
    different bases; scale the old one to the new at their first common month."""
    old_m, new_m = _monthly(old, "mean"), _monthly(new, "mean")
    common = old_m.index.intersection(new_m.index)
    if len(common) == 0:
        return new_m.rename("USD_BROAD")
    k = new_m.loc[common[:12]].mean() / old_m.loc[common[:12]].mean()
    out = pd.concat([old_m[old_m.index < new_m.index[0]] * k, new_m])
    return out.rename("USD_BROAD")


def component_values(raw: dict[str, pd.Series], grid: pd.DatetimeIndex,
                     point_in_time: bool = True) -> pd.DataFrame:
    """Signed component signals on a monthly grid. With point_in_time=False
    every lag is zero (used only for the 'latest reading' display)."""
    L = (lambda c: c.lag) if point_in_time else (lambda c: 0)
    comp = {c.key: c for f in FACTORS for c in f.components}
    out = {}

    gdp = _quarterly_shift(raw["A191RL1Q225SBEA"])
    out["gdp_growth"] = _known_at(gdp, L(comp["gdp_growth"]), grid)

    ff = _monthly(raw["FEDFUNDS"])
    core = _monthly(raw["CPILFESL"])
    core_yoy = core.pct_change(12, fill_method=None) * 100
    ff_known = _known_at(ff, L(comp["ff_change_6m"]), grid)
    out["ff_change_6m"] = -(ff_known - ff_known.shift(6))
    real_ff = _known_at(ff, L(comp["real_ff"]), grid) - _known_at(core_yoy, L(comp["real_ff"]), grid)
    out["real_ff"] = -real_ff

    out["core_cpi_gap"] = -(_known_at(core_yoy, L(comp["core_cpi_gap"]), grid) - 2.0).abs()

    cp = raw["CP"]
    cp_yoy = _quarterly_shift(cp.pct_change(4, fill_method=None) * 100)
    out["profits_yoy"] = _known_at(cp_yoy, L(comp["profits_yoy"]), grid)
    user = sources.user_eps()
    if user is not None:  # FactSet/LSEG override, 2-month publication lag
        eps_yoy = user.pct_change(4, fill_method=None) * 100
        eps_yoy.index = eps_yoy.index - pd.offsets.MonthBegin(1)
        override = _known_at(eps_yoy.dropna(), 2 if point_in_time else 0, grid)
        out["profits_yoy"] = override.combine_first(out["profits_yoy"])

    usd = raw["USD_BROAD"]
    usd_6m = usd.pct_change(6, fill_method=None) * 100
    out["usd_6m"] = -_known_at(usd_6m, L(comp["usd_6m"]), grid)

    sloos = _quarterly_shift(raw["DRTSCILM"])
    out["sloos"] = -_known_at(sloos, L(comp["sloos"]), grid)
    bc = _monthly(raw["TOTBKCR"], "mean")
    out["bank_credit_yoy"] = _known_at(bc.pct_change(12, fill_method=None) * 100,
                                       L(comp["bank_credit_yoy"]), grid)
    m2 = _monthly(raw["M2SL"])
    out["m2_yoy"] = _known_at(m2.pct_change(12, fill_method=None) * 100, L(comp["m2_yoy"]), grid)
    return pd.DataFrame(out, index=grid)


# ------------------------------------------------------------------ scoring

def expanding_percentile(x: pd.Series, min_periods: int = MIN_HISTORY) -> pd.Series:
    """Percentile (0-100) of each value among all values up to and including
    that date. Ties count half."""
    vals = x.to_numpy(dtype=float)
    out = np.full(len(vals), np.nan)
    hist: list[float] = []
    for i, v in enumerate(vals):
        if np.isnan(v):
            continue
        hist.append(v)
        if len(hist) >= min_periods:
            h = np.asarray(hist)
            out[i] = 100.0 * ((h < v).sum() + 0.5 * (h == v).sum()) / len(h)
    return pd.Series(out, index=x.index, name=x.name)


def score_against(history: pd.Series, value: float) -> float:
    h = history.dropna().to_numpy()
    if len(h) < MIN_HISTORY or np.isnan(value):
        return np.nan
    return 100.0 * ((h < value).sum() + 0.5 * (h == value).sum()) / len(h)


def factor_scores(comps: pd.DataFrame) -> pd.DataFrame:
    pct = comps.apply(expanding_percentile)
    out = {}
    for f in FACTORS:
        out[f.key] = pct[[c.key for c in f.components]].mean(axis=1, skipna=True)
    return pd.DataFrame(out)


def composite(fs: pd.DataFrame, weights: dict[str, float] | None = None,
              min_factors: int = 4) -> pd.Series:
    w = pd.Series({f.key: (weights or {}).get(f.key, f.weight) for f in FACTORS})
    w = w[w > 0]
    sub = fs[w.index]
    have = sub.notna()
    num = (sub.fillna(0) * w).sum(axis=1)
    den = (have * w).sum(axis=1)
    out = num / den.replace(0, np.nan)
    out[have.sum(axis=1) < min(min_factors, len(w))] = np.nan
    return out.rename("health")


# ------------------------------------------------------------------- market

def market_index(raw: dict[str, pd.Series], offline: bool = False) -> pd.DataFrame:
    """Monthly S&P 500 total-return index from Shiller's data (monthly average
    prices + dividends) spliced to FRED SP500 monthly averages for recent
    months. Also returns the T-bill rate for cash."""
    sh = sources.shiller(offline)
    spx = raw["SP500"].dropna()
    g = spx.groupby(spx.index.to_period("M"))
    fred_p, n_days = g.mean(), g.size()
    fred_p.index = fred_p.index.to_timestamp() + pd.offsets.MonthEnd(0)
    n_days.index = fred_p.index
    # Use FRED from its first complete month (>= 15 trading days) onward.
    # Shiller's final month is often a single early-month close rather than a
    # monthly average (Sep 2024 was 1.8% off), so FRED takes over where it can.
    full = n_days[n_days >= 15].index
    cut = full[0] if len(full) else fred_p.index[-1] + pd.offsets.MonthEnd(1)
    new = fred_p[fred_p.index >= cut]
    p = pd.concat([sh["P"][sh["P"].index < cut], new])
    # Dividends: Shiller D is an annual rate. After it ends, hold the last
    # known dividend yield constant (flagged on the Data page).
    d = sh["D"].reindex(p.index)
    last = sh["D"].last_valid_index()
    yld = (sh["D"] / sh["P"]).loc[last]
    est = d.isna() & (d.index > last)
    d[est] = p[est] * yld
    tr = (p + d / 12) / p.shift(1)
    tr.iloc[0] = 1.0
    df = pd.DataFrame({"price": p, "tr_index": tr.cumprod(), "div_estimated": est})
    tb = _monthly(raw["TB3MS"])
    tb.index = tb.index + pd.offsets.MonthEnd(0)
    df["tbill"] = tb.reindex(df.index).ffill()
    df.attrs["dividends_estimated_after"] = last
    df.attrs["fred_splice_start"] = new.index[0] if len(new) else None
    return df


@dataclass
class Model:
    comps: pd.DataFrame
    factors: pd.DataFrame
    health: pd.Series
    market: pd.DataFrame
    latest: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)
    recent: pd.DataFrame | None = None


def build(offline: bool = False, weights: dict | None = None, start: str = "1960-01-31") -> Model:
    raw = load_raw(offline)
    end = pd.Timestamp.today() + pd.offsets.MonthEnd(0)
    grid = pd.date_range(start, end, freq="ME")
    comps = component_values(raw, grid, point_in_time=True)
    fs = factor_scores(comps)
    health = composite(fs, weights)
    mkt = market_index(raw, offline)

    # Latest reading: newest published value of each component (no lag),
    # scored against the point-in-time history.
    now = component_values(raw, grid, point_in_time=False)
    latest = {}
    for f in FACTORS:
        parts = {}
        for c in f.components:
            v = now[c.key].dropna()
            val = float(v.iloc[-1]) if len(v) else np.nan
            parts[c.key] = {"label": c.label, "value": val,
                            "score": score_against(comps[c.key], val), "series": c.series}
        sc = np.nanmean([p["score"] for p in parts.values()]) if parts else np.nan
        latest[f.key] = {"label": f.label, "score": sc, "parts": parts, "why": f.why}
    w = {f.key: (weights or {}).get(f.key, f.weight) for f in FACTORS}
    tot = sum(w[k] for k in latest if not np.isnan(latest[k]["score"]) and w[k] > 0)
    latest["_health"] = sum(latest[k]["score"] * w[k] for k in w
                            if not np.isnan(latest[k]["score"]) and w[k] > 0) / tot
    return Model(comps, fs, health, mkt, latest, raw, recent_scores(comps, now, weights))


def recent_scores(comps: pd.DataFrame, now: pd.DataFrame, weights: dict | None = None,
                  months: int = 25) -> pd.DataFrame:
    """Factor scores and gauge for recent month-ends on the SAME basis as
    today's reading: newest data for each period, scored against the
    point-in-time history up to that month. All "change over N months"
    figures use this, so they compare like with like. (The point-in-time
    series, with conservative publication lags, is kept for the backtest.)"""
    w = {f.key: (weights or {}).get(f.key, f.weight) for f in FACTORS}
    rows = {}
    for t in now.index[-months:]:
        row = {}
        for f in FACTORS:
            sc = [score_against(comps[c.key].loc[:t], now[c.key].loc[t]) for c in f.components]
            row[f.key] = np.nanmean(sc) if not all(np.isnan(sc)) else np.nan
        ok = {k: v for k, v in row.items() if not np.isnan(v) and w[k] > 0}
        row["health"] = sum(v * w[k] for k, v in ok.items()) / sum(w[k] for k in ok) if ok else np.nan
        rows[t] = row
    return pd.DataFrame(rows).T
