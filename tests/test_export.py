import json
import math

import pandas as pd
import pytest

from mhd import export, meta


def test_clean_handles_nan_dates_numpy():
    import numpy as np
    from datetime import date
    out = export._clean({"a": np.float64("nan"), "b": np.int64(3), "c": pd.Timestamp("2026-01-31"),
                         "d": date(2026, 2, 1), "e": [np.bool_(True), 1.234567]})
    assert out == {"a": None, "b": 3, "c": "2026-01-31", "d": "2026-02-01", "e": [True, 1.2346]}
    json.dumps(out)


def test_change_rate_in_bp_and_level_in_pct():
    idx = pd.date_range("2026-01-01", periods=40, freq="D")
    s = pd.Series(range(40), index=idx, dtype=float) / 100 + 4.0   # 4.00 -> 4.39
    assert math.isclose(export._change(s, 7, "rate"), 7.0, abs_tol=1e-9)
    lv = pd.Series(100.0, index=idx); lv.iloc[-1] = 110.0
    assert math.isclose(export._change(lv, 7, "level"), 10.0)


def test_parse_fred_page_fields():
    page = ('<title>Thing Index (ABC) | FRED</title>'
            '<strong>Source:</strong> <a class="x" href="https://agency.gov">Agency Name\n<i></i></a>'
            '<strong>Release:</strong> <a class="y" href="https://agency.gov/rel">Release Name <i></i></a>'
            '<strong>Units:</strong>&nbsp;<span class="series-meta-value"><span class="series-meta-value-units">Percent</span>, SA</p>'
            '<strong>Frequency:</strong> <span class="series-meta-value"><span class="series-meta-value-frequency"> Monthly </span>'
            '<span class="series-meta-updated-date">Oct 1, 2026</span> <span class="series-meta-updated-time">8:00 AM CDT</span>')
    m = meta._parse("ABC", page)
    assert m["title"] == "Thing Index" and m["source"] == "Agency Name" and m["release"] == "Release Name"
    assert m["units"] == "Percent, SA" and m["frequency"] == "Monthly" and m["fred_updated"] == "Oct 1, 2026 8:00 AM CDT"


@pytest.mark.skipif(not (export.SITE / "data.json").exists(), reason="run mhd.export first")
def test_built_payload_is_complete():
    d = json.loads((export.SITE / "data.json").read_text())
    assert set(d) >= {"meta", "headline", "factors", "history", "markets", "backtest", "sources"}
    n = len(d["history"]["dates"])
    assert all(len(d["history"]["factors"][k]) == n for k in d["history"]["factors"])
    used = {p["series"] for f in d["factors"] for p in f["parts"]}
    cited = {s["id"] for s in d["sources"]}
    assert used <= cited                      # every series shown is cited
    assert all(s.get("title") for s in d["sources"])
    assert 0 <= d["headline"]["score"] <= 100
