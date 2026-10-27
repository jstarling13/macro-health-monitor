"""Client brief wording, built in Python so it can be tested and checked by
the publish gate (the site only renders what this produces).

Two rules keep the cards honest:
1. Every trend uses the same measure as the headline (model.recent_scores).
2. A card's sentence describes the latest reading, often over a different
   window than its 3-month trend. When the two point opposite ways (the
   dollar rose over six months but the picture improved recently), the card
   says so in plain words instead of leaving a contradiction.
"""
from __future__ import annotations

import math
import re

# Plain-language scale for clients (no letter grades).
TIERS = [(70, "Strong"), (55, "Good"), (45, "Average"), (25, "Below average"), (0, "Weak")]
TREND_MIN = 3.0   # score points over 3 months before we call it a trend


def tier(score: float) -> tuple[int, str]:
    for i, (cut, name) in enumerate(TIERS):
        if score >= cut:
            return i, name
    return len(TIERS) - 1, TIERS[-1][1]


def trend(change: float) -> int:
    return 1 if change > TREND_MIN else -1 if change < -TREND_MIN else 0


def _tone_from_tier(i: int) -> int:
    return 1 if i <= 1 else -1 if i >= 3 else 0


def _f(x, d=1):
    return f"{abs(x):.{d}f}"


def _area(key, name, score, change, text, tone):
    i, t = tier(score)
    tr = trend(change)
    note = None
    if tone < 0 and tr > 0:
        note = "Even so, this area has improved over the past three months."
    elif tone > 0 and tr < 0:
        note = "That said, it has softened over the past three months."
    return {"key": key, "name": name, "score": score, "change_3m": change, "tier": t, "tier_index": i,
            "trend": {1: "Improving", -1: "Weakening", 0: "Steady"}[tr], "trend_dir": tr,
            "tone": tone, "text": text + (" " + note if note else ""), "reconciled": note is not None}


def build(payload: dict) -> dict:
    F = {f["key"]: f for f in payload["factors"]}
    P = lambda f, k: next(p for p in F[f]["parts"] if p["key"] == k)["value"]
    sc = lambda k: F[k]["score"]
    ch = lambda k: F[k]["change_3m"]
    pick = lambda k, opts: opts[tier(sc(k))[0]]

    gdp, ffc = P("gdp", "gdp_growth"), P("fed", "ff_change_6m")
    cpi, prof = P("inflation", "core_cpi_gap"), P("earnings", "profits_yoy")
    usd, sl, bc = P("usd", "usd_6m"), P("credit", "sloos"), P("credit", "bank_credit_yoy")

    fed_move = (f"rose {ffc:.2f} points" if ffc > 0.05 else f"fell {abs(ffc):.2f} points" if ffc < -0.05 else "held steady")
    cpi_pos = "right around" if abs(cpi - 2) < 0.35 else "above" if cpi > 2 else "below"
    usd_note = ("A stronger dollar can weigh on U.S. companies that sell abroad." if usd >= 1.5 else
                "A softer dollar helps U.S. companies that sell abroad." if usd <= -1.5 else "That is a fairly normal move.")
    areas = [
        _area("gdp", "Economic growth", sc("gdp"), ch("gdp"),
              f"The economy grew at a {gdp:.1f}% yearly pace last quarter, " + pick("gdp", [
                  "well above its usual pace.", "a bit faster than usual.", "close to its usual pace.",
                  "somewhat slower than usual.", "well below its usual pace."]),
              _tone_from_tier(tier(sc("gdp"))[0])),
        _area("fed", "Interest rates", sc("fed"), ch("fed"),
              pick("fed", ["Rates are low or falling, which supports borrowing and spending.", "Rate policy is mildly supportive.",
                           "Rate policy is roughly neutral.", "Rates lean restrictive, which can slow borrowing.",
                           "Rates are high or rising, a headwind for borrowing."]) + f" Over six months the Fed's key rate {fed_move}.",
              _tone_from_tier(tier(sc("fed"))[0])),
        _area("inflation", "Inflation", sc("inflation"), ch("inflation"),
              f"Prices are rising {cpi:.1f}% a year, excluding food and energy, {cpi_pos} the Fed's 2% goal.",
              1 if cpi_pos == "right around" else (-1 if abs(cpi - 2) > 1 else 0)),
        _area("earnings", "Company profits", sc("earnings"), ch("earnings"),
              f"Corporate profits are {'up' if prof >= 0 else 'down'} {_f(prof)}% from a year ago, " + pick("earnings", [
                  "strong growth.", "solid growth.", "about normal.", "softer than usual.", "a weak showing."]),
              _tone_from_tier(tier(sc("earnings"))[0])),
        _area("usd", "The dollar", sc("usd"), ch("usd"),
              f"The dollar has {'risen' if usd >= 0 else 'fallen'} {_f(usd)}% over six months. {usd_note}",
              -1 if usd >= 1.5 else 1 if usd <= -1.5 else 0),
        _area("credit", "Lending", sc("credit"), ch("credit"),
              f"Banks are {'tightening' if sl > 2 else 'easing' if sl < -2 else 'holding steady on'} their lending standards, "
              f"and total bank lending is up {bc:.1f}% from a year ago. " + pick("credit", [
                  "Credit is flowing freely.", "Credit conditions are healthy.", "Credit conditions are about normal.",
                  "Credit is a little tighter than usual.", "Credit is tight."]),
              _tone_from_tier(tier(sc("credit"))[0])),
    ]
    hd = payload["headline"]
    hi, ht = tier(hd["score"])
    best = max(areas, key=lambda a: a["score"])
    worst = min(areas, key=lambda a: a["score"])
    verb = lambda a: "are" if a["name"].endswith("s") else "is"
    return {
        "score": hd["score"], "tier": ht, "tier_index": hi,
        "headline": ["The economy is in strong shape overall.", "The economy is in good shape overall.",
                     "The economy is in average shape: some areas are strong while others are soft.",
                     "The economy is somewhat softer than usual.", "The economy is under strain."][hi],
        "detail": f"{best['name']} {verb(best)} the brightest spot, while {worst['name'].lower()} {verb(worst)} the softest.",
        "areas": areas,
        "better": [a["name"] for a in areas if a["trend_dir"] > 0],
        "worse": [a["name"] for a in areas if a["trend_dir"] < 0],
    }


def problems(client: dict, payload: dict) -> list[str]:
    """Contradictions or broken text a reader would notice. Used by the gate."""
    out = []
    F = {f["key"]: f for f in payload["factors"]}
    for a in client["areas"]:
        if re.search(r"\b(nan|None|undefined|inf|NaN)\b", a["text"]) or not a["text"].strip():
            out.append(f"{a['name']}: text is broken ({a['text']!r})")
        if a["tone"] * a["trend_dir"] < 0 and not a["reconciled"]:
            out.append(f"{a['name']}: sentence and 3-month trend point opposite ways with no explanation")
        if not math.isclose(a["score"], F[a["key"]]["score"], abs_tol=0.01):
            out.append(f"{a['name']}: card score differs from the factor score")
        if a["trend_dir"] != trend(F[a["key"]]["change_3m"]):
            out.append(f"{a['name']}: trend arrow does not match the factor's 3-month change")
    if set(client["better"]) & set(client["worse"]):
        out.append("An area is listed as both getting better and getting weaker")
    if client["tier"] != tier(payload["headline"]["score"])[1]:
        out.append("Headline label does not match the headline score")
    return out
