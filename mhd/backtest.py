"""Does the Health Gauge predict the market?

Timing: the gauge is computed at the end of month t from data known then.
Prices are monthly averages, so the earliest fair entry is month t+1's
average. Forward h-month return = TR[t+1+h] / TR[t+1] - 1. Nothing in the
model was fitted to returns: weights are equal and grade cut-offs were set
before looking at results, so the test is not curve-fit (though the factor
choices themselves reflect hindsight about what usually matters).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats


def forward_returns(tr: pd.Series, horizons=(1, 3, 6, 12)) -> pd.DataFrame:
    entry = tr.shift(-1)
    return pd.DataFrame({f"fwd_{h}m": tr.shift(-1 - h) / entry - 1 for h in horizons})


def newey_west_t(y: np.ndarray, x: np.ndarray, lags: int) -> tuple[float, float]:
    """Slope and HAC t-stat of y on x. Overlapping 12-month returns are highly
    autocorrelated; plain t-stats would overstate significance ~3x."""
    X = np.column_stack([np.ones_like(x), x])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    u = y - X @ beta
    n = len(y)
    XtX_inv = np.linalg.inv(X.T @ X)
    S = (X * u[:, None]).T @ (X * u[:, None])
    for l in range(1, lags + 1):
        w = 1 - l / (lags + 1)
        G = (X[l:] * u[l:, None]).T @ (X[:-l] * u[:-l, None])
        S += w * (G + G.T)
    V = XtX_inv @ S @ XtX_inv
    return float(beta[1]), float(beta[1] / np.sqrt(V[1, 1]))


def predictive_stats(signal: pd.Series, fwd: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for col in fwd:
        h = int(col.split("_")[1][:-1])
        d = pd.concat([signal, fwd[col]], axis=1).dropna()
        if len(d) < 60:
            continue
        x, y = d.iloc[:, 0].to_numpy(), d.iloc[:, 1].to_numpy()
        rho, _ = stats.spearmanr(x, y)
        slope, t = newey_west_t(y, x, max(h - 1, 0) + 2)
        rows.append({"horizon": f"{h}m", "months": len(d), "rank_corr": rho,
                     "ret_per_10pts": slope * 10, "nw_t_stat": t,
                     "significant_5pct": abs(t) > 1.96})
    return pd.DataFrame(rows)


def bucket_table(signal: pd.Series, fwd: pd.Series, cuts=(0, 35, 45, 60, 70, 101)) -> pd.DataFrame:
    labels = ["F (<35)", "D (35-45)", "C (45-60)", "B (60-70)", "A (70+)"]
    d = pd.concat([signal.rename("s"), fwd.rename("r")], axis=1).dropna()
    d["bucket"] = pd.cut(d["s"], bins=list(cuts), labels=labels, right=False)
    g = d.groupby("bucket", observed=False)["r"]
    return pd.DataFrame({"months": g.size(), "avg_return": g.mean(), "median_return": g.median(),
                         "pct_positive": g.apply(lambda r: (r > 0).mean() if len(r) else np.nan),
                         "worst": g.min()})


def strategy(signal: pd.Series, mkt: pd.DataFrame, threshold: float = 45.0) -> pd.DataFrame:
    """In stocks when the gauge at end of month t >= threshold, else T-bills,
    for month t+1 -> t+2 (one month of implementation delay)."""
    tr = mkt["tr_index"]
    stock_ret = (tr.shift(-2) / tr.shift(-1) - 1)
    cash_ret = (mkt["tbill"] / 100 / 12).shift(-1)
    d = pd.DataFrame({"signal": signal, "stock": stock_ret, "cash": cash_ret}).dropna()
    d["in_market"] = d["signal"] >= threshold
    d["strategy"] = np.where(d["in_market"], d["stock"], d["cash"])
    d["switch"] = d["in_market"].astype(int).diff().abs().fillna(0)
    return d


def perf(r: pd.Series, rf: pd.Series | None = None) -> dict:
    r = r.dropna()
    if r.empty:
        return {}
    eq = (1 + r).cumprod()
    yrs = len(r) / 12
    ex = r - (rf.reindex(r.index).fillna(0) if rf is not None else 0)
    sd = ex.std()
    return {"CAGR": eq.iloc[-1] ** (1 / yrs) - 1, "vol": r.std() * np.sqrt(12),
            "sharpe": (ex.mean() * 12) / (sd * np.sqrt(12)) if sd > 0 else np.nan,
            "max_drawdown": (eq / eq.cummax() - 1).min(), "growth_of_1": eq.iloc[-1]}


def summary(signal: pd.Series, mkt: pd.DataFrame, threshold: float = 45.0) -> dict:
    fwd = forward_returns(mkt["tr_index"]).reindex(signal.index)
    s = strategy(signal, mkt, threshold)
    by_decade = []
    for dec, g in s.groupby((s.index.year // 10) * 10):
        by_decade.append({"decade": f"{dec}s", "strategy_cagr": perf(g["strategy"]).get("CAGR"),
                          "buy_hold_cagr": perf(g["stock"]).get("CAGR"),
                          "pct_time_invested": g["in_market"].mean()})
    return {
        "stats": predictive_stats(signal, fwd),
        "buckets_12m": bucket_table(signal, fwd["fwd_12m"]),
        "buckets_3m": bucket_table(signal, fwd["fwd_3m"]),
        "strategy": s,
        "perf": pd.DataFrame({"Gauge timing": perf(s["strategy"], s["cash"]),
                              "Buy & hold S&P 500": perf(s["stock"], s["cash"]),
                              "T-bills": perf(s["cash"], s["cash"])}).T,
        "by_decade": pd.DataFrame(by_decade),
        "switches_per_year": s["switch"].sum() / (len(s) / 12),
        "fwd": fwd,
    }


def factor_diagnostics(factors: pd.DataFrame, health: pd.Series, mkt: pd.DataFrame) -> pd.DataFrame:
    """12-month rank correlation and HAC t-stat for each factor alone, the
    gauge, and the gauge's 6-month change. Exploratory: with this many tests,
    one |t| > 2 can appear by chance."""
    fwd = forward_returns(mkt["tr_index"], (12,)).reindex(health.index)["fwd_12m"]
    sigs = {**{c: factors[c] for c in factors}, "health": health,
            "health_6m_change": health - health.shift(6)}
    rows = []
    for k, x in sigs.items():
        d = pd.concat([x, fwd], axis=1).dropna()
        if len(d) < 60:
            continue
        rho, _ = stats.spearmanr(d.iloc[:, 0], d.iloc[:, 1])
        slope, t = newey_west_t(d.iloc[:, 1].to_numpy(), d.iloc[:, 0].to_numpy(), 13)
        rows.append({"signal": k, "months": len(d), "rank_corr_12m": rho, "nw_t_stat": t})
    return pd.DataFrame(rows)
