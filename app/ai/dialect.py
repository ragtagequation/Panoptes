"""Offer language vs buyer dialect gap."""

from __future__ import annotations

from collections import Counter
from typing import Any

from app.ai.nlp import bag, clip, jaccard, tokenize
from app.ai.synthesis import BUZZWORDS


def dialect_gap(offer: str, leads: list[dict[str, Any]]) -> dict[str, Any]:
    offer = (offer or "").strip()
    if not offer:
        return {"error": "Provide an offer.", "gap_score": 0}
    if not leads:
        return {"error": "No asks to compare against.", "gap_score": 0}

    offer_terms = set(tokenize(offer))
    buyer_bag: Counter[str] = Counter()
    for lead in leads:
        buyer_bag.update(tokenize(_text(lead)))

    buyer_top = [t for t, _ in buyer_bag.most_common(40)]
    buyer_set = set(buyer_top)

    overlap = offer_terms & buyer_set
    only_you = offer_terms - buyer_set
    only_them = buyer_set - offer_terms

    # Gap score: 0 = perfect dialect match, 100 = speaking different languages
    if not offer_terms:
        gap = 100
    else:
        jac = jaccard(offer_terms, buyer_set)
        buzz = len(only_you & BUZZWORDS) / max(1, len(only_you)) if only_you else 0
        gap = int(round(100 * (0.7 * (1 - jac) + 0.3 * buzz)))

    # Migration map: replace your words with their nearest buyer equivalents
    migrations = []
    for yours in sorted(only_you)[:12]:
        # Find buyer term with highest char overlap
        best, best_s = None, 0.0
        for theirs in buyer_top[:25]:
            s = jaccard(set(yours), set(theirs))  # char-set proxy
            # prefer length-similar
            s *= 1.0 - abs(len(yours) - len(theirs)) / max(len(yours), len(theirs), 1)
            if s > best_s:
                best, best_s = theirs, s
        if best and best_s > 0.15:
            migrations.append({"from": yours, "to": best, "strength": round(best_s, 2)})
        elif yours in BUZZWORDS:
            migrations.append({"from": yours, "to": "(drop — buzzword)", "strength": 1.0})

    label = "aligned" if gap < 30 else "drifting" if gap < 55 else "foreign"

    rewritten_hint = " ".join(
        (next((m["to"] for m in migrations if m["from"] == t and not m["to"].startswith("(")), t)
         for t in tokenize(offer, stem_words=False)[:20])
    )

    return {
        "gap_score": gap,
        "label": label,
        "overlap_words": sorted(overlap)[:12],
        "your_only": sorted(only_you)[:12],
        "buyer_only": [t for t in buyer_top if t in only_them][:12],
        "migrations": migrations[:10],
        "buzzwords_in_offer": sorted(only_you & BUZZWORDS),
        "rewrite_hint": rewritten_hint[:240],
        "insight": _insight(gap, label, overlap, only_them),
        "error": "",
    }


def _insight(gap: int, label: str, overlap: set, only_them: set) -> str:
    if label == "aligned":
        return f"Dialect gap {gap}/100 — you're already speaking their language ({len(overlap)} shared terms)."
    if label == "drifting":
        top = ", ".join(list(only_them)[:4])
        return f"Dialect gap {gap}/100 — drifting. Adopt buyer words like: {top}."
    top = ", ".join(list(only_them)[:5])
    return (
        f"Dialect gap {gap}/100 — foreign dialect. Campaigns will underperform until you "
        f"migrate to: {top}."
    )


def _text(lead: dict[str, Any]) -> str:
    return " ".join(str(lead.get(k) or "") for k in ("ask_quote", "evidence", "what_they_do"))
