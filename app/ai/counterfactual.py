"""Counterfactual Demand — rescore the corpus under an alternate offer.

Ask: 'what if I sold X instead of Y?' Most tools validate one idea.
This simulates demand fit under a hypothetical offer without re-scraping,
by re-ranking existing asks with BM25 against the counterfactual wording.
"""

from __future__ import annotations

from typing import Any

from app.ai.match import match_summary, rank_asks
from app.ai.synthesis import compute_signal


def counterfactual(
    current_offer: str,
    alternate_offer: str,
    leads: list[dict[str, Any]],
) -> dict[str, Any]:
    current_offer = (current_offer or "").strip()
    alternate_offer = (alternate_offer or "").strip()
    if not alternate_offer:
        return {"error": "Provide an alternate offer to simulate."}
    if not leads:
        return {"error": "No asks stored — run a scan first."}

    base = rank_asks(current_offer or alternate_offer, leads, limit=30) if current_offer else []
    alt = rank_asks(alternate_offer, leads, limit=30)
    base_sum = match_summary(base) if base else {"top_fit": 0, "avg_fit": 0, "decision_ready": 0, "hire_intent": 0}
    alt_sum = match_summary(alt)

    delta_avg = alt_sum["avg_fit"] - base_sum.get("avg_fit", 0)
    delta_top = alt_sum["top_fit"] - base_sum.get("top_fit", 0)

    # Asks that jump into the top under the alternate
    base_ids = {r["ask_id"] for r in base[:10]}
    unlocked = [r for r in alt[:10] if r["ask_id"] not in base_ids]
    lost = [r for r in base[:10] if r["ask_id"] not in {a["ask_id"] for a in alt[:10]}]

    verdict = (
        "stronger" if delta_avg >= 8
        else "weaker" if delta_avg <= -8
        else "similar"
    )

    signal = compute_signal(leads)
    return {
        "verdict": verdict,
        "delta_avg_fit": delta_avg,
        "delta_top_fit": delta_top,
        "current": {"offer": current_offer, **base_sum},
        "alternate": {"offer": alternate_offer, **alt_sum},
        "unlocked_asks": unlocked[:5],
        "lost_asks": lost[:5],
        "corpus_stats": signal,
        "insight": _insight(verdict, delta_avg, unlocked, alternate_offer),
        "error": "",
    }


def _insight(verdict: str, delta: int, unlocked: list, alt: str) -> str:
    if verdict == "stronger":
        return (
            f"Counterfactual '{alt[:60]}' fits the corpus {delta:+d} avg-fit points better "
            f"and unlocks {len(unlocked)} asks your current offer misses."
        )
    if verdict == "weaker":
        return (
            f"Alternate offer is {delta:+d} avg-fit — stick with the current wording "
            "or narrow the niche before pivoting."
        )
    return "Alternate offer is roughly equivalent — difference is in which specific asks you unlock."
