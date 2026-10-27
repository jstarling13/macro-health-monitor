"""Macro Health Dashboard -- Streamlit app.

Run:  .venv/bin/streamlit run app.py
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from mhd import backtest, model, sources

warnings.filterwarnings("ignore")
st.set_page_config(page_title="Macro Health Dashboard", page_icon="📈", layout="wide")

COLORS = {"gdp": "#2a6f97", "fed": "#8e5bd0", "inflation": "#d1495b", "earnings": "#2e933c",
          "usd": "#e09f3e", "credit": "#4f6d7a", "health": "#111827"}


@st.cache_data(ttl=6 * 3600, show_spinner="Pulling FRED and Shiller data…")
def load(weights: tuple, offline: bool):
    sources.LOG.rows.clear()
    m = model.build(offline=offline, weights=dict(weights))
    return m, list(sources.LOG.rows)


# ------------------------------------------------------------------ sidebar
st.sidebar.header("Factor weights")
st.sidebar.caption("Equal weights are the default and what the backtest was designed around.")
weights = tuple((f.key, st.sidebar.slider(f.label, 0.0, 3.0, 1.0, 0.25)) for f in model.FACTORS)
threshold = st.sidebar.slider("Backtest: hold stocks when gauge ≥", 20, 80, 45, 5)
offline = st.sidebar.toggle("Use cached data only", value=False,
                            help="Skip downloads and use data/cache. For outages or demos.")
if st.sidebar.button("Refresh data now"):
    for p in sources.CACHE.glob("*"):
        if p.suffix in {".csv", ".xls"}:
            # Back-date instead of deleting, so a failed download still has a cache.
            import os
            os.utime(p, (0, 0))
    st.cache_data.clear()

m, log = load(weights, offline)
L = m.latest
health = L["_health"]
g, word = model.grade(health)
start = m.factors.dropna().index[0]

st.title("Macro Health Dashboard")
st.caption("GDP, Fed policy, inflation, corporate earnings, the U.S. dollar, and credit & liquidity, "
           "each scored 0–100 against all history known at the time. 50 = historically average.")

tab_now, tab_hist, tab_bt, tab_data = st.tabs(["Today", "History", "Backtest", "Data & method"])

# -------------------------------------------------------------------- today
with tab_now:
    c1, c2 = st.columns([1, 2])
    with c1:
        fig = go.Figure(go.Indicator(
            mode="gauge+number", value=health, number={"suffix": f" {g}", "valueformat": ".0f", "font": {"size": 34}},
            title={"text": f"Health Gauge · {word}"},
            gauge={"axis": {"range": [0, 100]}, "bar": {"color": "#111827"},
                   "steps": [{"range": [0, 35], "color": "#f4c7c3"}, {"range": [35, 45], "color": "#fbe3c4"},
                             {"range": [45, 60], "color": "#eef0f2"}, {"range": [60, 70], "color": "#d5ecd4"},
                             {"range": [70, 100], "color": "#b7e1b5"}]}))
        fig.update_layout(height=300, margin=dict(l=20, r=20, t=60, b=10))
        st.plotly_chart(fig, use_container_width=True)
        prev = m.health.dropna()
        if len(prev) > 3:
            st.metric("Point-in-time gauge, 3 months ago", f"{prev.iloc[-4]:.0f}",
                      f"{health - prev.iloc[-4]:+.1f} since")
    with c2:
        rows = []
        for f in model.FACTORS:
            d = L[f.key]
            fg, fw = model.grade(d["score"])
            rows.append({"Factor": d["label"], "Score": d["score"], "Grade": fg, "Reading": fw,
                         "Why it matters": d["why"]})
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True,
                     column_config={"Score": st.column_config.ProgressColumn(min_value=0, max_value=100,
                                                                             format="%.0f")})
        weakest = min((f for f in model.FACTORS), key=lambda f: L[f.key]["score"])
        strongest = max((f for f in model.FACTORS), key=lambda f: L[f.key]["score"])
        st.info(f"**Biggest drag:** {weakest.label} ({L[weakest.key]['score']:.0f}).  "
                f"**Biggest support:** {strongest.label} ({L[strongest.key]['score']:.0f}).")

    st.subheader("Latest readings")
    det = []
    for f in model.FACTORS:
        for k, p in L[f.key]["parts"].items():
            det.append({"Factor": f.label, "Measure": p["label"], "Latest value": p["value"],
                        "Score": p["score"], "FRED series": p["series"]})
    st.dataframe(pd.DataFrame(det), hide_index=True, use_container_width=True,
                 column_config={"Latest value": st.column_config.NumberColumn(format="%.2f"),
                                "Score": st.column_config.NumberColumn(format="%.0f")})
    st.caption("Signed values: measures where lower is better (rate hikes, real rates, distance from 2% "
               "inflation, dollar strength, loan tightening) are shown with a minus sign so that "
               "higher always means better for stocks.")

# ------------------------------------------------------------------ history
with tab_hist:
    since = st.select_slider("From", options=[1980, 1990, 2000, 2010, 2015, 2020], value=2000)
    h = m.health.loc[str(since):]
    px = m.market["price"].loc[str(since):]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=h.index, y=h, name="Health Gauge", line=dict(color=COLORS["health"], width=2)))
    fig.add_trace(go.Scatter(x=px.index, y=px, name="S&P 500 (right)", yaxis="y2",
                             line=dict(color="#9ca3af", width=1.5)))
    for lo, hi, col in [(0, 35, "rgba(209,73,91,.08)"), (70, 100, "rgba(46,147,60,.08)")]:
        fig.add_hrect(y0=lo, y1=hi, fillcolor=col, line_width=0)
    fig.update_layout(height=420, yaxis=dict(range=[0, 100], title="Gauge"),
                      yaxis2=dict(overlaying="y", side="right", type="log", title="S&P 500", showgrid=False),
                      legend=dict(orientation="h", y=1.08), margin=dict(t=30))
    st.plotly_chart(fig, use_container_width=True)

    fig2 = go.Figure()
    for f in model.FACTORS:
        s = m.factors[f.key].loc[str(since):].rolling(3).mean()
        fig2.add_trace(go.Scatter(x=s.index, y=s, name=f.label, line=dict(color=COLORS[f.key], width=1.6)))
    fig2.update_layout(height=420, yaxis=dict(range=[0, 100], title="Factor score (3-mo avg)"),
                       legend=dict(orientation="h", y=1.1), margin=dict(t=30))
    st.plotly_chart(fig2, use_container_width=True)

# ----------------------------------------------------------------- backtest
with tab_bt:
    bt = backtest.summary(m.health.loc[start:], m.market, threshold)
    st.subheader("Does the gauge predict the market?")
    st.write(f"{len(bt['strategy'])} months, {start:%b %Y} to present. The gauge at each month-end uses only "
             "data published by then; the trade happens the following month.")
    s12 = bt["stats"].set_index("horizon").loc["12m"]
    verdict = ("No. Across horizons the gauge's link to future returns is weak and not statistically significant."
               if not bt["stats"]["significant_5pct"].any() else
               "Some horizons are statistically significant; see the table.")
    st.markdown(f"**Short answer: {verdict}** 12-month rank correlation {s12.rank_corr:+.2f} "
                f"(Newey-West t = {s12.nw_t_stat:.2f}; |t| > 1.96 needed).")

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Average next-12-month S&P 500 total return, by gauge grade**")
        b = bt["buckets_12m"].reset_index()
        fig = go.Figure(go.Bar(x=b["bucket"].astype(str), y=b["avg_return"] * 100,
                               text=[f"{v*100:.1f}%<br>n={n}" for v, n in zip(b["avg_return"], b["months"])],
                               textposition="outside", marker_color="#2a6f97"))
        fig.update_layout(height=340, yaxis_title="%", margin=dict(t=10))
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        st.markdown(f"**Timing rule: stocks when gauge ≥ {threshold}, else T-bills**")
        s = bt["strategy"]
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=s.index, y=(1 + s["stock"]).cumprod(), name="Buy & hold"))
        fig.add_trace(go.Scatter(x=s.index, y=(1 + s["strategy"]).cumprod(), name="Gauge timing"))
        fig.update_layout(height=340, yaxis_type="log", yaxis_title="Growth of $1",
                          legend=dict(orientation="h", y=1.1), margin=dict(t=10))
        st.plotly_chart(fig, use_container_width=True)

    perf = bt["perf"].copy()
    st.dataframe(perf.style.format({"CAGR": "{:.1%}", "vol": "{:.1%}", "sharpe": "{:.2f}",
                                    "max_drawdown": "{:.1%}", "growth_of_1": "{:,.0f}"}),
                 use_container_width=True)
    st.caption(f"Switches per year: {bt['switches_per_year']:.1f}. No trading costs or taxes included.")

    c3, c4 = st.columns(2)
    with c3:
        st.markdown("**By decade**")
        st.dataframe(bt["by_decade"].style.format({"strategy_cagr": "{:.1%}", "buy_hold_cagr": "{:.1%}",
                                                   "pct_time_invested": "{:.0%}"}),
                     hide_index=True, use_container_width=True)
    with c4:
        st.markdown("**Each factor on its own (12-month horizon)**")
        fd = backtest.factor_diagnostics(m.factors.loc[start:], m.health.loc[start:], m.market)
        st.dataframe(fd.style.format({"rank_corr_12m": "{:+.2f}", "nw_t_stat": "{:+.2f}"}),
                     hide_index=True, use_container_width=True)
        st.caption("Exploratory. Eight tests at once, so one |t| near 2 could be luck.")
    st.markdown("**All horizons**")
    st.dataframe(bt["stats"].style.format({"rank_corr": "{:+.3f}", "ret_per_10pts": "{:+.2%}",
                                           "nw_t_stat": "{:+.2f}"}), hide_index=True, use_container_width=True)

# --------------------------------------------------------------------- data
with tab_data:
    st.subheader("Download status")
    st.dataframe(pd.DataFrame(log), hide_index=True, use_container_width=True)
    da = m.market.attrs.get("dividends_estimated_after")
    st.caption(f"S&P 500 prices: Shiller monthly averages, then FRED SP500 from "
               f"{m.market.attrs.get('fred_splice_start'):%b %Y}. Dividends after {da:%b %Y} are estimated "
               "at the last known yield.")
    st.subheader("Method")
    st.markdown("""
- **Scores.** Each measure is signed so higher is better for stocks, then scored as its percentile against
  every earlier month (needs 5 years of history). A factor is the average of its measures; the gauge is the
  weighted average of factors. Grades: A ≥ 70, B ≥ 60, C ≥ 45, D ≥ 35, F below.
- **No look-ahead.** A reading enters the model only after its usual publication delay
  (e.g. GDP 4 months after the quarter starts, corporate profits 6 months, CPI 1 month).
- **Earnings.** BEA corporate profits after tax (FRED `CP`) cover all U.S. companies, so the gauge no longer
  depends on how many tickers an API returns. To use S&P 500 EPS from FactSet or LSEG instead, save
  `data/sp500_eps.csv` with columns `date,eps` (quarter-end, 4-quarter trailing EPS).
- **Dollar.** FRED broad trade-weighted index (`DTWEXBGS`), spliced to `TWEXBMTH` before 2006. The ICE DXY
  is not freely available; the broad index tracks it closely and covers more trading partners. A weaker dollar
  scores higher.
- **Credit & liquidity.** Bank regulation (capital and reserve rules) works through bank lending, so the model
  tracks its effect: the Fed's Senior Loan Officer Survey (`DRTSCILM`), bank credit growth (`TOTBKCR`) and M2.
- **Caveats.** FRED serves today's revised GDP and profits, not first prints. Monthly-average prices smooth
  returns slightly. Results are research, not investment advice.
""")
    with st.expander("Raw component values (point-in-time)"):
        st.dataframe(m.comps.loc[start:].iloc[::-1], use_container_width=True)
