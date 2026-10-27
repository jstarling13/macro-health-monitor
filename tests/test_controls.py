"""The safety controls must actually stop bad data. Each test breaks something
on purpose and checks the control catches it."""
import copy
import json
from datetime import datetime

import pandas as pd
import pytest

from mhd import export, sources, validate

DATA = export.SITE / "data.json"
pytestmark = pytest.mark.skipif(not DATA.exists(), reason="run mhd.export first")


@pytest.fixture
def good():
    d = json.loads(DATA.read_text())
    return d, datetime.strptime(d["meta"]["generated_at"], "%Y-%m-%dT%H:%MZ")


def test_current_build_passes(good):
    d, when = good
    r = validate.run(d, None, when)
    assert r["ok"], r["errors"]


def test_blocks_missing_headline(good):
    d, when = good
    d["headline"]["score"] = None
    assert not validate.run(d, None, when)["ok"]


def test_blocks_out_of_range_factor(good):
    d, when = good
    d["factors"][0]["score"] = 140.0
    assert not validate.run(d, None, when)["ok"]


def test_blocks_truncated_history(good):
    d, when = good
    for k in ["dates", "health", "spx", "recession"]:
        d["history"][k] = d["history"][k][-100:]
    assert not validate.run(d, None, when)["ok"]


def test_blocks_gap_in_recent_gauge(good):
    d, when = good
    d["history"]["health"][-3] = None
    assert not validate.run(d, None, when)["ok"]


def test_blocks_uncited_series(good):
    d, when = good
    d["sources"] = [s for s in d["sources"] if s["id"] != "CP"]
    assert not validate.run(d, None, when)["ok"]


def test_blocks_badly_stale_input(good):
    d, when = good
    for s in d["sources"]:
        if s["id"] == "CPILFESL":
            s["last_obs"] = "2025-01-01"
    r = validate.run(d, None, when)
    assert not r["ok"] and any("CPILFESL" in e for e in r["errors"])


def test_big_move_blocks_unless_overridden(good, monkeypatch):
    d, when = good
    prev = {"date": "2000-01-01", "health": d["headline"]["score"] + 30,
            **{f["key"]: f["score"] for f in d["factors"]}}
    assert not validate.run(copy.deepcopy(d), prev, when)["ok"]
    monkeypatch.setenv("MHD_ALLOW_BIG_MOVE", "1")
    assert validate.run(copy.deepcopy(d), prev, when)["ok"]


def test_stale_market_series_is_a_warning_not_a_block(good):
    d, when = good
    d["markets"][0]["as_of"] = "2020-01-01"
    r = validate.run(d, None, when)
    assert r["ok"] and any(d["markets"][0]["label"] in w for w in r["warnings"])


def test_download_guard_rejects_truncated_series():
    idx = pd.date_range("1990-01-01", periods=400, freq="MS")
    old = pd.Series(1.0, index=idx)
    assert sources._shrunk(old, old) is None
    assert "rows" in sources._shrunk(old, old.iloc[:300])
    later_start = pd.Series(1.0, index=pd.date_range("1992-01-01", periods=400, freq="MS"))
    assert "starts" in sources._shrunk(old, later_start)
    went_back = pd.Series(1.0, index=pd.date_range("1989-10-01", periods=400, freq="MS"))
    assert "backwards" in sources._shrunk(old, went_back)


# ---- consistency of change figures and client wording ---------------------

from mhd import brief


def _scenario(good, key, score=None, change=None, part=None, value=None):
    d = copy.deepcopy(good[0])
    f = next(x for x in d["factors"] if x["key"] == key)
    if score is not None:
        f["score"] = score
    if change is not None:
        f["change_3m"] = change
        d["history"]["recent"][key][-4] = f["score"] - change
    if part:
        next(p for p in f["parts"] if p["key"] == part)["value"] = value
    d["history"]["recent"][key][-1] = f["score"]
    return d


def test_dollar_up_but_improving_is_explained_not_contradictory(good):
    # The original bug: dollar rose (bad) while the arrow said Improving.
    d = _scenario(good, "usd", score=40, change=+10, part="usd_6m", value=2.5)
    card = next(a for a in brief.build(d)["areas"] if a["key"] == "usd")
    assert card["trend"] == "Improving" and card["tone"] < 0
    assert card["reconciled"] and "improved over the past three months" in card["text"]


def test_strong_but_weakening_is_explained(good):
    d = _scenario(good, "earnings", score=85, change=-12)
    card = next(a for a in brief.build(d)["areas"] if a["key"] == "earnings")
    assert card["reconciled"] and "softened" in card["text"]


def test_gate_blocks_mixed_basis_change(good):
    d, when = copy.deepcopy(good[0]), good[1]
    d["client"] = brief.build(d)
    next(f for f in d["factors"] if f["key"] == "usd")["change_3m"] += 25   # a lagged-series figure sneaks in
    r = validate.run(d, None, when)
    assert not r["ok"] and any("same measure" in e for e in r["errors"])


def test_gate_blocks_headline_change_from_wrong_series(good):
    d, when = copy.deepcopy(good[0]), good[1]
    d["client"] = brief.build(d)
    d["headline"]["change_3m"] = d["headline"]["change_3m"] + 6
    assert not validate.run(d, None, when)["ok"]


def test_gate_blocks_unexplained_contradiction(good):
    d, when = copy.deepcopy(good[0]), good[1]
    c = brief.build(d)
    a = c["areas"][0]
    a.update(tone=-1, trend_dir=1, trend="Improving", reconciled=False)   # simulate the wording rule being removed
    d["client"] = c
    next(f for f in d["factors"] if f["key"] == a["key"])["change_3m"] = 10
    r = validate.run(d, None, when)
    assert not r["ok"] and any("opposite ways" in e for e in r["errors"])


def test_gate_blocks_broken_text(good):
    d, when = copy.deepcopy(good[0]), good[1]
    c = brief.build(d)
    c["areas"][2]["text"] = "Prices are rising nan% a year."
    d["client"] = c
    assert not validate.run(d, None, when)["ok"]


def test_every_tier_and_trend_combination_is_coherent(good):
    """Sweep all scores and trends for every area: no card may be left
    with a sentence and an arrow that disagree."""
    for f in good[0]["factors"]:
        for score in (10, 30, 50, 60, 80):
            for change in (-15, 0, 15):
                d = _scenario(good, f["key"], score=score, change=change)
                c = brief.build(d)
                assert not [p for p in brief.problems(c, d) if "opposite ways" in p], (f["key"], score, change)
