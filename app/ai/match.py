"""Offer-ask ranking via BM25 + char n-grams."""

from __future__ import annotations

from collections import Counter
from typing import Any

from app.ai.intel import analyze_ask
from app.ai.nlp import bag, bm25_score, char_ngrams, clip, jaccard


def rank_asks(
    offer: str,
    leads: list[dict[str, Any]],
    *,
    limit: int = 25,
) -> list[dict[str, Any]]:
    offer = (offer or "").strip()
    if not offer or not leads:
        return []

    q_bag = bag(offer)
    q_chars = char_ngrams(offer, 3)
    docs = [bag(_text(l)) for l in leads]
    df: Counter[str] = Counter()
    for d in docs:
        df.update(set(d))
    avgdl = (sum(sum(d.values()) for d in docs) / len(docs)) if docs else 1.0
    n = len(docs)

    ranked: list[dict[str, Any]] = []
    for lead, doc in zip(leads, docs):
        bm = bm25_score(q_bag, doc, df, n, avgdl)
        # Normalize BM25 roughly into 0..1 via soft squashing
        bm_n = bm / (bm + 4.0) if bm > 0 else 0.0
        jac = jaccard(q_chars, char_ngrams(_text(lead), 3))
        silence = int(lead.get("silence_score") or 0) / 100
        intel = analyze_ask(lead)
        # Weighted fusion — BM25 dominates, char-ngrams catch paraphrases,
        # silence + priority pull the warmest asks up.
        fit = 100 * (
            0.45 * bm_n
            + 0.20 * jac
            + 0.20 * silence
            + 0.15 * (intel["priority_score"] / 100)
        )
        ranked.append({
            "ask_id": lead.get("ask_id") or "",
            "username": lead.get("username") or "",
            "quote": clip(lead.get("ask_quote") or lead.get("evidence") or "", 220),
            "url": lead.get("ask_url") or "",
            "fit_score": int(round(fit)),
            "bm25": round(bm, 3),
            "char_overlap": round(jac, 3),
            "silence_score": int(lead.get("silence_score") or 0),
            "intent": intel["intent"],
            "buying_stage": intel["buying_stage"],
            "urgency": intel["urgency"],
            "reply_odds": intel["reply_odds"],
            "priority_score": intel["priority_score"],
            "email": lead.get("email") or "",
            "phone": lead.get("phone") or "",
        })

    ranked.sort(key=lambda r: (-r["fit_score"], -r["silence_score"]))
    return ranked[: max(0, limit)]


def match_summary(ranked: list[dict[str, Any]]) -> dict[str, Any]:
    if not ranked:
        return {
            "top_fit": 0,
            "avg_fit": 0,
            "decision_ready": 0,
            "hire_intent": 0,
            "contactable_top": 0,
        }
    top = ranked[:10]
    return {
        "top_fit": top[0]["fit_score"],
        "avg_fit": int(round(sum(r["fit_score"] for r in top) / len(top))),
        "decision_ready": sum(1 for r in ranked if r["buying_stage"] == "decision"),
        "hire_intent": sum(1 for r in ranked if r["intent"] == "hire"),
        "contactable_top": sum(1 for r in top if r.get("email") or r.get("phone")),
    }


def _text(lead: dict[str, Any]) -> str:
    return " ".join(
        str(lead.get(k) or "")
        for k in ("ask_quote", "evidence", "what_they_do", "site_title", "context")
    )
