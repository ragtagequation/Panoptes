"""Outcome memory — case-based retrieval that learns from what you tagged.

When you mark asks as booked / replied / ignored, those outcomes become a
training signal. New asks retrieve the nearest past wins (BM25 + char n-grams)
so solutions and drafts can imitate what actually converted — a free RAG loop
with no vector DB.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from app.ai.nlp import bag, bm25_score, char_ngrams, clip, jaccard

POSITIVE = {"booked", "replied", "won", "converted", "meeting", "closed"}
NEGATIVE = {"ignored", "lost", "bounced", "unqualified", "spam"}


def retrieve_cases(
    lead: dict[str, Any],
    corpus: list[dict[str, Any]],
    *,
    limit: int = 5,
) -> dict[str, Any]:
    """Find the most similar past asks that have an outcome tag."""
    cases = [c for c in corpus if (c.get("outcome") or "").strip()]
    if not cases:
        return {
            "cases": [],
            "win_rate": None,
            "insight": "No tagged outcomes yet — mark asks as booked/replied/ignored to train this loop.",
            "patterns": [],
        }

    q_bag = bag(_text(lead))
    q_chars = char_ngrams(_text(lead), 3)
    docs = [bag(_text(c)) for c in cases]
    df: Counter[str] = Counter()
    for d in docs:
        df.update(set(d))
    avgdl = (sum(sum(d.values()) for d in docs) / len(docs)) if docs else 1.0
    n = len(docs)

    scored: list[dict[str, Any]] = []
    for case, doc in zip(cases, docs):
        bm = bm25_score(q_bag, doc, df, n, avgdl)
        jac = jaccard(q_chars, char_ngrams(_text(case), 3))
        sim = 0.7 * (bm / (bm + 3.0) if bm > 0 else 0.0) + 0.3 * jac
        outcome = (case.get("outcome") or "").strip().lower()
        polarity = (
            "win" if any(p in outcome for p in POSITIVE)
            else "loss" if any(p in outcome for p in NEGATIVE)
            else "other"
        )
        scored.append({
            "ask_id": case.get("ask_id") or "",
            "username": case.get("username") or "",
            "quote": clip(case.get("ask_quote") or case.get("evidence") or "", 180),
            "outcome": case.get("outcome") or "",
            "polarity": polarity,
            "similarity": int(round(100 * sim)),
            "url": case.get("ask_url") or "",
        })

    scored.sort(key=lambda s: -s["similarity"])
    top = scored[:limit]

    wins = sum(1 for c in cases if any(p in (c.get("outcome") or "").lower() for p in POSITIVE))
    win_rate = round(100 * wins / len(cases), 1) if cases else None
    patterns = _extract_patterns(cases)

    insight = (
        f"{len(cases)} tagged outcomes · win rate {win_rate}%. "
        + (f"Nearest win: “{top[0]['quote']}”." if top and top[0]["polarity"] == "win" else "")
        + (" Tag more outcomes to sharpen retrieval." if len(cases) < 8 else "")
    )

    return {
        "cases": top,
        "win_rate": win_rate,
        "tagged": len(cases),
        "patterns": patterns,
        "insight": insight.strip(),
    }


def training_signal(corpus: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate what converts — used by the cockpit / README metrics."""
    cases = [c for c in corpus if (c.get("outcome") or "").strip()]
    if not cases:
        return {"tagged": 0, "wins": 0, "losses": 0, "win_rate": None, "top_win_words": []}

    wins = [c for c in cases if any(p in (c.get("outcome") or "").lower() for p in POSITIVE)]
    losses = [c for c in cases if any(p in (c.get("outcome") or "").lower() for p in NEGATIVE)]

    win_bag: Counter[str] = Counter()
    loss_bag: Counter[str] = Counter()
    for c in wins:
        win_bag.update(bag(_text(c)))
    for c in losses:
        loss_bag.update(bag(_text(c)))

    # Words enriched in wins vs losses
    scored = []
    for term, wc in win_bag.items():
        lc = loss_bag.get(term, 0)
        lift = (wc + 0.5) / (lc + 0.5)
        if wc >= 2:
            scored.append((lift, term, wc))
    scored.sort(reverse=True)

    return {
        "tagged": len(cases),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(100 * len(wins) / len(cases), 1) if cases else None,
        "top_win_words": [t for _, t, _ in scored[:8]],
        "top_loss_words": [
            t for _, t, _ in sorted(
                (((loss_bag[t] + 0.5) / (win_bag.get(t, 0) + 0.5), t) for t in loss_bag if loss_bag[t] >= 2),
                reverse=True,
            )[:6]
        ],
    }


def _extract_patterns(cases: list[dict[str, Any]]) -> list[str]:
    wins = [c for c in cases if any(p in (c.get("outcome") or "").lower() for p in POSITIVE)]
    if len(wins) < 2:
        return []
    from app.ai.intel import analyze_ask

    intents = Counter(analyze_ask(c)["intent"] for c in wins)
    stages = Counter(analyze_ask(c)["buying_stage"] for c in wins)
    patterns = []
    if intents:
        top_i, n = intents.most_common(1)[0]
        patterns.append(f"Wins skew toward intent={top_i} ({n}/{len(wins)})")
    if stages:
        top_s, n = stages.most_common(1)[0]
        patterns.append(f"Wins skew toward stage={top_s} ({n}/{len(wins)})")
    contactable = sum(1 for c in wins if c.get("email") or c.get("phone"))
    if contactable:
        patterns.append(f"{contactable}/{len(wins)} wins had public contact on file")
    return patterns


def _text(lead: dict[str, Any]) -> str:
    return " ".join(
        str(lead.get(k) or "")
        for k in ("ask_quote", "evidence", "what_they_do", "site_title", "draft_public", "draft_dm")
    )
