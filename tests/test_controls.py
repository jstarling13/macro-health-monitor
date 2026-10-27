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
