"""ICP fingerprint from tagged win outcomes."""

from __future__ import annotations

from collections import Counter
from typing import Any

from app.ai.intel import analyze_ask
from app.ai.memory import NEGATIVE, POSITIVE
from app.ai.nlp import bag, clip


def discover_icp(leads: list[dict[str, Any]]) -> dict[str, Any]:
    wins = [l for l in leads if _polarity(l) == "win"]
    losses = [l for l in leads if _polarity(l) == "loss"]
    if len(wins) < 2:
        return {
            "ready": False,
            "wins": len(wins),
            "losses": len(losses),
            "insight": "Tag at least 2 booked/replied outcomes to auto-discover an ICP.",
            "fingerprint": {},
            "anti_fingerprint": {},
        }

    win_intel = [analyze_ask(w) for w in wins]
    loss_intel = [analyze_ask(l) for l in losses] if losses else []

    intent_c = Counter(i["intent"] for i in win_intel)
    stage_c = Counter(i["buying_stage"] for i in win_intel)
    win_words: Counter[str] = Counter()
    loss_words: Counter[str] = Counter()
    for w in wins:
        win_words.update(bag(_text(w)))
    for l in losses:
        loss_words.update(bag(_text(l)))

    lift = []
    for term, wc in win_words.items():
        lc = loss_words.get(term, 0)
        if wc >= 2:
            lift.append(((wc + 0.5) / (lc + 0.5), term, wc))
    lift.sort(reverse=True)

    contact_rate = sum(1 for w in wins if w.get("email") or w.get("phone")) / len(wins)
    avg_urgency = int(sum(i["urgency"] for i in win_intel) / len(win_intel))
    avg_silence = int(
        sum(int(w.get("silence_score") or 0) for w in wins) / len(wins)
    )

    fingerprint = {
        "top_intent": intent_c.most_common(1)[0][0] if intent_c else "",
        "top_stage": stage_c.most_common(1)[0][0] if stage_c else "",
        "intent_mix": dict(intent_c),
        "stage_mix": dict(stage_c),
        "signature_words": [t for _, t, _ in lift[:10]],
        "avg_urgency": avg_urgency,
        "avg_silence": avg_silence,
        "contact_rate": round(100 * contact_rate, 1),
        "examples": [
            clip(w.get("ask_quote") or w.get("evidence") or "", 140) for w in wins[:3]
        ],
    }

    anti = []
    for term, lc in loss_words.items():
        wc = win_words.get(term, 0)
        if lc >= 2 and lc > wc:
            anti.append(((lc + 0.5) / (wc + 0.5), term))
    anti.sort(reverse=True)

    return {
        "ready": True,
        "wins": len(wins),
        "losses": len(losses),
        "fingerprint": fingerprint,
        "anti_fingerprint": {"avoid_words": [t for _, t in anti[:8]]},
        "insight": (
            f"ICP from {len(wins)} wins: intent={fingerprint['top_intent']}, "
            f"stage={fingerprint['top_stage']}, urgency≈{avg_urgency}, "
            f"signature words: {', '.join(fingerprint['signature_words'][:5])}."
        ),
    }


def score_against_icp(lead: dict[str, Any], icp: dict[str, Any]) -> dict[str, Any]:
    """How well does this ask match the learned ICP?"""
    fp = icp.get("fingerprint") or {}
    if not fp:
        return {"icp_fit": 0, "reason": "ICP not ready"}
    intel = analyze_ask(lead)
    score = 40
    reasons = []
    if intel["intent"] == fp.get("top_intent"):
        score += 20
        reasons.append("intent match")
    if intel["buying_stage"] == fp.get("top_stage"):
        score += 15
        reasons.append("stage match")
    words = set(bag(_text(lead)))
    sig = set(fp.get("signature_words") or [])
    hit = len(words & sig)
    score += min(20, hit * 5)
    if hit:
        reasons.append(f"{hit} signature words")
    avoid = set((icp.get("anti_fingerprint") or {}).get("avoid_words") or [])
    bad = len(words & avoid)
    score -= min(25, bad * 8)
    if bad:
        reasons.append(f"{bad} anti-words")
    return {
        "icp_fit": int(max(0, min(100, score))),
        "reason": ", ".join(reasons) or "weak match",
        "intel": {
            "intent": intel["intent"],
            "buying_stage": intel["buying_stage"],
            "urgency": intel["urgency"],
        },
    }


def _polarity(lead: dict[str, Any]) -> str:
    o = (lead.get("outcome") or "").strip().lower()
    if any(p in o for p in POSITIVE):
        return "win"
    if any(p in o for p in NEGATIVE):
        return "loss"
    return "none"


def _text(lead: dict[str, Any]) -> str:
    return " ".join(str(lead.get(k) or "") for k in ("ask_quote", "evidence", "what_they_do", "context"))
