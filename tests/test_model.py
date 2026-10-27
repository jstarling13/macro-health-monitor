import numpy as np
import pandas as pd

from mhd import backtest, model


def test_known_at_respects_lag():
    s = pd.Series([1.0, 2.0], index=pd.to_datetime(["2020-01-01", "2020-02-01"]))
    grid = pd.date_range("2019-12-31", "2020-06-30", freq="ME")
    k = model._known_at(s, 2, grid)
    assert np.isnan(k["2020-02-29"])           # Jan value not known until end of March
    assert k["2020-03-31"] == 1.0
    assert k["2020-04-30"] == 2.0


def test_quarterly_shift_moves_to_quarter_end_month():
    s = pd.Series([5.0], index=pd.to_datetime(["2026-04-01"]))  # Q2
    assert model._quarterly_shift(s).index[0] == pd.Timestamp("2026-06-01")


def test_expanding_percentile_has_no_lookahead():
    x = pd.Series(np.arange(100, dtype=float))
    p1 = model.expanding_percentile(x)
    x2 = x.copy(); x2.iloc[80:] = -1000  # changing the future must not change the past
    p2 = model.expanding_percentile(x2)
    pd.testing.assert_series_equal(p1.iloc[:80], p2.iloc[:80])
    assert p1.iloc[:59].isna().all() and p1.iloc[99] > 99


def test_composite_weights_and_min_factors():
    fs = pd.DataFrame({f.key: [50.0, np.nan] for f in model.FACTORS})
    fs.loc[0, "gdp"] = 100.0
    w = {f.key: 1.0 for f in model.FACTORS}
    c = model.composite(fs, w)
    assert abs(c.iloc[0] - (100 + 50 * 5) / 6) < 1e-9
    assert np.isnan(c.iloc[1])


def test_splice_dollar_is_continuous():
    idx_old = pd.date_range("2000-01-01", "2007-12-01", freq="MS")
    idx_new = pd.date_range("2006-01-02", "2010-12-31", freq="B")
    old = pd.Series(50.0, index=idx_old)
    new = pd.Series(100.0, index=idx_new)
    s = model.splice_dollar(old, new)
    assert abs(s.loc["2005-12-01"] - 100.0) < 1e-9 and s.index.is_monotonic_increasing


def test_forward_returns_enter_next_month():
    tr = pd.Series([100, 110, 121, 133.1], index=pd.date_range("2020-01-31", periods=4, freq="ME"))
    f = backtest.forward_returns(tr, (1,))
    assert abs(f["fwd_1m"].iloc[0] - 0.10) < 1e-9  # signal Jan -> buy Feb avg, sell Mar avg


def test_newey_west_recovers_slope():
    rng = np.random.default_rng(0)
    x = rng.normal(size=500); y = 0.5 * x + rng.normal(scale=0.1, size=500)
    b, t = backtest.newey_west_t(y, x, 5)
    assert abs(b - 0.5) < 0.02 and t > 20


def test_grades():
    assert model.grade(75)[0] == "A" and model.grade(50)[0] == "C" and model.grade(10)[0] == "F"


def test_drop_crisis_removes_overlapping_forward_windows():
    idx = pd.date_range("2006-01-31", "2010-12-31", freq="ME")
    drop = backtest._drop_crisis(idx, "2008-09", "2008-12")
    assert drop["2007-09-30"] and drop["2008-12-31"]          # window touches the crisis
    assert not drop["2007-07-31"] and not drop["2009-01-31"]  # fully before / after


def test_recession_odds_by_quintile():
    idx = pd.date_range("1980-01-31", periods=200, freq="ME")
    signal = pd.Series(np.linspace(0, 100, 200), index=idx)
    rec = pd.Series(0.0, index=idx); rec.iloc[:40] = 1.0          # recessions only at the low end
    ro = backtest.recession_odds(signal, rec)
    shares = [r["recession_share"] for r in ro["rows"]]
    assert len(shares) == 5 and shares[0] > 0.9 and shares[-1] == 0.0


def test_recent_scores_match_latest_reading():
    """Today's headline and the 'recent' series must be the same measure,
    or change figures mix bases (the dollar once showed -22 when it rose)."""
    m = model.build(offline=True)
    assert abs(m.recent["health"].iloc[-1] - m.latest["_health"]) < 1e-9
    for f in model.FACTORS:
        assert abs(m.recent[f.key].iloc[-1] - m.latest[f.key]["score"]) < 1e-9
