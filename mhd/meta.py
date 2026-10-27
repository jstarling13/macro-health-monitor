"""Source citations, read from each FRED series page (not typed by hand).

Cached in data/cache/meta.json for 7 days. If a page can't be read, the
citation falls back to the series ID and FRED link only.
"""
from __future__ import annotations

import html
import json
import re
import time

from . import sources

PATH = sources.CACHE / "meta.json"
MAX_AGE = 7 * 24 * 3600


def _txt(s: str | None) -> str | None:
    if s is None:
        return None
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", s))).strip() or None


def _parse(sid: str, page: str) -> dict:
    def grab(pattern):
        m = re.search(pattern, page, re.S)
        return m
    title = grab(r"<title>(.*?)\s*\(" + re.escape(sid) + r"\)")
    src = grab(r"<strong>Source:</strong>\s*<a[^>]*href=\"([^\"]+)\"[^>]*>(.*?)<i")
    rel = grab(r"<strong>Release:</strong>\s*<a[^>]*href=\"([^\"]+)\"[^>]*>(.*?)<i")
    units = grab(r"<strong>Units:</strong>.*?series-meta-value-units\">(.*?)</p>")
    freq = grab(r"<strong>Frequency:</strong>.*?series-meta-value-frequency\">(.*?)</span>")
    upd = grab(r"series-meta-updated-date\">([^<]+)</span>\s*<span class=\"series-meta-updated-time\">([^<]+)<")
    return {
        "id": sid,
        "title": _txt(title.group(1)) if title else None,
        "source": _txt(src.group(2)) if src else None,
        "source_url": src.group(1) if src else None,
        "release": _txt(rel.group(2)) if rel else None,
        "release_url": rel.group(1) if rel else None,
        "units": _txt(units.group(1)) if units else None,
        "frequency": _txt(freq.group(1)) if freq else None,
        "fred_updated": f"{upd.group(1)} {upd.group(2)}" if upd else None,
        "url": f"https://fred.stlouisfed.org/series/{sid}",
    }


def fred_meta(ids: list[str], offline: bool = False) -> dict[str, dict]:
    cache = json.loads(PATH.read_text()) if PATH.exists() else {}
    fresh = PATH.exists() and time.time() - PATH.stat().st_mtime < MAX_AGE
    out = {}
    for sid in ids:
        if sid in cache and (fresh or offline):
            out[sid] = cache[sid]
            continue
        try:
            page = sources._get(f"https://fred.stlouisfed.org/series/{sid}").decode("utf-8", "replace")
            out[sid] = _parse(sid, page)
        except Exception:
            out[sid] = cache.get(sid) or {"id": sid, "url": f"https://fred.stlouisfed.org/series/{sid}"}
    cache.update(out)
    PATH.write_text(json.dumps(cache, indent=1))
    return out


SHILLER = {
    "id": "SHILLER", "title": "U.S. Stock Price, Dividend and Earnings Data (monthly, since 1871)",
    "source": "Robert J. Shiller, Yale University", "source_url": "https://shillerdata.com/",
    "release": "Online data accompanying 'Irrational Exuberance'", "units": "Index level; dividends and earnings in index points",
    "frequency": "Monthly", "url": "https://shillerdata.com/",
}
