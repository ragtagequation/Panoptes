"""Compile an offer into pain language + demand search queries."""

from __future__ import annotations

import re
from typing import Any


DEMAND_PREFIXES = [
    "looking for",
    "need",
    "anyone know",
    "recommend",
    "recommendations for",
    "how do I find",
    "where can I find",
    "seeking",
    "hiring",
    "in the market for",
    "struggling with",
    "help with",
]

COMMERCIAL_HINTS = [
    "agency",
    "freelancer",
    "consultant",
    "service",
    "setter",
    "appointment",
    "leads",
    "book calls",
    "VA",
    "outsource",
]


def compile_offer(offer: str, *, niche: str = "", company: str = "") -> dict[str, Any]:
    offer = (offer or "").strip()
    niche = (niche or "").strip()
    company = (company or "").strip()
    if not offer and not niche:
        raise ValueError("offer or niche is required")

    base = niche or _infer_niche(offer)
    pains = _pain_phrases(offer, base)
    queries = _build_queries(offer, base, pains, company)

    return {
        "offer": offer,
        "niche": base,
        "company": company,
        "pain_phrases": pains,
        "queries": queries,
        "channel_default": "email_then_call" if "appointment" in offer.lower() or "setter" in offer.lower() else "call_or_email",
    }


def _infer_niche(offer: str) -> str:
    # crude: words after "for" / "helping"
    m = re.search(r"\b(?:for|helping|with)\s+(.+)$", offer, re.I)
    if m:
        return m.group(1).strip().rstrip(".")
    return offer.strip()


def _pain_phrases(offer: str, niche: str) -> list[str]:
    o = offer.lower()
    phrases = [
        f"looking for {niche}",
        f"need {niche}",
        f"recommend {niche}",
        f"anyone use {niche}",
        f"best {niche}",
        f"struggling with {niche}",
    ]
    if any(w in o for w in ("appointment", "setter", "book calls", "booking")):
        phrases.extend([
            "looking for appointment setter",
            "need someone to book calls",
            "hiring a setter",
            "appointment setting help",
            "can't book enough calls",
        ])
    if any(w in o for w in ("lead", "leads", "outbound")):
        phrases.extend([
            "leads drying up",
            "need more leads",
            "outbound not working",
        ])
    if any(w in o for w in ("agency", "marketing", "coach")):
        phrases.extend([
            f"{niche} agency recommendations",
            f"hiring a {niche} agency",
        ])

    # de-dupe
    out, seen = [], set()
    for p in phrases:
        k = p.lower()
        if k not in seen:
            seen.add(k)
            out.append(p)
    return out[:16]


def _build_queries(offer: str, niche: str, pains: list[str], company: str) -> list[str]:
    queries = []
    for p in pains[:8]:
        queries.append(p)
    queries.append(f'"{niche}" ("looking for" OR "need" OR "recommend" OR "anyone know")')
    queries.append(f"{niche} (help OR struggling OR hiring OR seeking)")
    if company:
        queries.append(f"{company} alternative OR instead of OR switching from")
    # web demand surfaces (free search — Google/Yahoo/Bing via existing websearch)
    queries.append(f'{niche} "looking for" OR "RFP" OR "need a vendor"')
    queries.append(f'site:instagram.com "{niche}" (looking OR need OR recommend)')
    queries.append(f'site:linkedin.com/in "{niche}" (looking OR hiring OR need)')
    queries.append(f'(site:x.com OR site:twitter.com) "{niche}" (looking for OR need OR recommend)')
    queries.append(f'site:facebook.com "{niche}" (looking for OR recommend OR need)')
    out, seen = [], set()
    for q in queries:
        k = q.lower()
        if k not in seen:
            seen.add(k)
            out.append(q)
    return out[:16]
