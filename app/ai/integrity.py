"""Evidence Integrity — every AI claim must cite a real ask.

Competitors say 'evidence-backed' then hallucinate. This verifier checks that
quoted fragments actually appear (fuzzy) in stored asks, and scores claim
integrity. A quiet but important moat for trustworthy demand AI.
"""

from __future__ import annotations

import re
from typing import Any

from app.ai.nlp import clip


def verify_claims(
    claims: list[dict[str, Any]],
    leads: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    claims: [{claim, evidence?}] — evidence is a supposed quote fragment.
    Returns per-claim support status + corpus integrity score.
    """
    corpus_text = [_text(l) for l in leads]
    results = []
    supported = 0
    for c in claims:
        claim = str(c.get("claim") or "").strip()
        evidence = str(c.get("evidence") or "").strip()
        if not evidence:
            results.append({
                "claim": claim,
                "evidence": "",
                "status": "unsupported",
                "overlap": 0,
                "matched_ask_id": "",
            })
            continue
        best_id, best_ov = "", 0.0
        for lead, text in zip(leads, corpus_text):
            ov = _fuzzy_overlap(evidence, text)
            if ov > best_ov:
                best_ov = ov
                best_id = lead.get("ask_id") or ""
        status = "verified" if best_ov >= 0.55 else "weak" if best_ov >= 0.30 else "unsupported"
        if status == "verified":
            supported += 1
        results.append({
            "claim": claim,
            "evidence": clip(evidence, 160),
            "status": status,
            "overlap": round(best_ov, 3),
            "matched_ask_id": best_id,
        })

    n = len(results) or 1
    integrity = int(round(100 * supported / n))
    return {
        "claims": results,
        "integrity_score": integrity,
        "verified": supported,
        "total": len(results),
        "insight": (
            f"Evidence integrity {integrity}/100 — {supported}/{len(results)} claims "
            "trace to a real stored ask."
            if results else "No claims to verify."
        ),
    }


def verify_brief_pains(brief: dict[str, Any], leads: list[dict[str, Any]]) -> dict[str, Any]:
    """Auto-check top_pains + voice_of_customer from a demand brief."""
    claims = []
    for p in brief.get("top_pains") or []:
        if isinstance(p, dict):
            claims.append({"claim": p.get("pain") or "", "evidence": p.get("evidence") or ""})
    for v in brief.get("voice_of_customer") or []:
        claims.append({"claim": "voice_of_customer", "evidence": str(v)})
    return verify_claims(claims, leads)


def _fuzzy_overlap(needle: str, hay: str) -> float:
    n = re.sub(r"\s+", " ", (needle or "").lower()).strip()
    h = re.sub(r"\s+", " ", (hay or "").lower()).strip()
    if not n or not h:
        return 0.0
    if n in h:
        return 1.0
    # token overlap
    nw = set(re.findall(r"[a-z0-9']{3,}", n))
    hw = set(re.findall(r"[a-z0-9']{3,}", h))
    if not nw:
        return 0.0
    return len(nw & hw) / len(nw)


def _text(lead: dict[str, Any]) -> str:
    return " ".join(str(lead.get(k) or "") for k in ("ask_quote", "evidence", "what_they_do", "context"))
