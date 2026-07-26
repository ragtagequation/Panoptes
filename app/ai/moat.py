"""First-Responder Moat — estimate how long silence still has value.

Nobody else productizes this: competitors surface intent, but they don't tell
you *how many hours you have* before the crowd answers and the moat closes.

Model: fit a simple exponential decay on age × remaining silence for similar
asks, then project the expected reply-arrival time for a fresh unanswered ask.
"""

from __future__ import annotations

import math
from typing import Any

from app.ai.nlp import bag, bm25_score, clip
from collections import Counter


def first_responder_moat(
    lead: dict[str, Any],
    corpus: list[dict[str, Any]],
) -> dict[str, Any]:
    """Estimate remaining first-responder window for one ask."""
    age = _age(lead)
    comments = int(lead.get("num_comments") or 0)
    silence = int(lead.get("silence_score") or 0)

    # Neighbors by BM25 — learn typical reply timing from similar asks
    neighbors = _similar(lead, corpus, limit=12)
    half_life = _estimate_half_life(neighbors)  # hours until 50% get a reply

    # Probability that THIS ask is still unanswered after `t` more hours
    # P(still silent) ≈ exp(-ln2 * (age_hours + t) / half_life) scaled by current silence
    age_h = max(0.5, age * 24)
    sil_factor = max(0.15, silence / 100)

    def p_open(extra_h: float) -> float:
        return sil_factor * math.exp(-0.693 * (age_h + extra_h) / max(half_life, 1.0))

    # Moat hours = time until P(open) drops below 0.35
    moat_h = 0.0
    for h in range(0, 168):  # up to 7 days
        if p_open(float(h)) < 0.35:
            moat_h = float(h)
            break
    else:
        moat_h = 168.0

    urgency = "closing_fast" if moat_h <= 6 else "open_window" if moat_h <= 36 else "lingering"
    if comments >= 3:
        urgency = "already_contested"
        moat_h = 0.0

    return {
        "ask_id": lead.get("ask_id") or "",
        "moat_hours": round(moat_h, 1),
        "half_life_hours": round(half_life, 1),
        "p_still_open_6h": round(p_open(6), 3),
        "p_still_open_24h": round(p_open(24), 3),
        "urgency": urgency,
        "neighbors_used": len(neighbors),
        "insight": _insight(moat_h, urgency, half_life),
        "quote": clip(lead.get("ask_quote") or lead.get("evidence") or "", 160),
    }


def moat_board(leads: list[dict[str, Any]], *, limit: int = 15) -> dict[str, Any]:
    """Rank asks by closing moat — answer these before the window shuts."""
    scored = [first_responder_moat(l, leads) for l in leads]
    # Prefer high-value closing windows: short moat but still open
    open_ones = [s for s in scored if s["urgency"] in ("closing_fast", "open_window")]
    open_ones.sort(key=lambda s: (0 if s["urgency"] == "closing_fast" else 1, s["moat_hours"]))
    lingering = [s for s in scored if s["urgency"] == "lingering"]
    contested = [s for s in scored if s["urgency"] == "already_contested"]

    return {
        "closing_now": open_ones[:limit],
        "lingering": lingering[:5],
        "contested": contested[:5],
        "avg_moat_hours": round(
            sum(s["moat_hours"] for s in scored) / len(scored), 1
        ) if scored else 0,
        "insight": (
            f"{len(open_ones)} asks still have an open first-responder window; "
            f"{sum(1 for s in open_ones if s['urgency']=='closing_fast')} close within 6h."
            if open_ones else "No open first-responder windows in this set."
        ),
    }


def _estimate_half_life(neighbors: list[dict[str, Any]]) -> float:
    """
    Approximate half-life (hours) from neighbors that eventually got replies.
    Unanswered old asks push half-life up; fast-answered ones pull it down.
    """
    samples = []
    for n in neighbors:
        age_h = max(1.0, _age(n) * 24)
        comments = int(n.get("num_comments") or 0)
        if comments > 0:
            # Got a reply sometime within age — treat age as upper bound on TTR
            samples.append(age_h * 0.5)
        else:
            # Still unanswered after age_h → half-life at least this long
            samples.append(age_h * 1.2)
    if not samples:
        return 36.0  # default ~1.5 days
    return max(4.0, min(120.0, sum(samples) / len(samples)))


def _similar(lead: dict[str, Any], corpus: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    q = bag(_text(lead))
    docs = [bag(_text(c)) for c in corpus if c.get("ask_id") != lead.get("ask_id")]
    if not docs:
        return []
    df: Counter[str] = Counter()
    for d in docs:
        df.update(set(d))
    avgdl = sum(sum(d.values()) for d in docs) / len(docs)
    scored = []
    others = [c for c in corpus if c.get("ask_id") != lead.get("ask_id")]
    for c, d in zip(others, docs):
        s = bm25_score(q, d, df, len(docs), avgdl)
        if s > 0:
            scored.append((s, c))
    scored.sort(key=lambda x: -x[0])
    return [c for _, c in scored[:limit]]


def _age(lead: dict[str, Any]) -> float:
    try:
        return max(0.0, float(lead.get("age_days") if lead.get("age_days") is not None else 3))
    except Exception:
        return 3.0


def _insight(moat_h: float, urgency: str, half_life: float) -> str:
    if urgency == "already_contested":
        return "Thread already has replies — first-responder moat is gone; differentiate on depth."
    if urgency == "closing_fast":
        return f"~{moat_h:.0f}h left. Similar asks get answered with ~{half_life:.0f}h half-life — reply now."
    if urgency == "open_window":
        return f"Open window of ~{moat_h:.0f}h. You can still be first with a help-first answer."
    return f"Lingering ask (~{moat_h:.0f}h projected). Lower urgency, but still unanswered — good for public authority."


def _text(lead: dict[str, Any]) -> str:
    return " ".join(str(lead.get(k) or "") for k in ("ask_quote", "evidence", "what_they_do", "context"))
