"""Score how unanswered a public ask is."""

from __future__ import annotations

import time
from typing import Any


def silence_score(
    *,
    num_comments: int = 0,
    created_utc: float | None = None,
    title: str = "",
    body: str = "",
) -> dict[str, Any]:
    """
    Higher = more valuable unanswered demand.
    0-100.
    """
    comments = max(0, int(num_comments or 0))
    text = f"{title} {body}".lower()

    if comments == 0:
        base = 92
        label = "zero_replies"
    elif comments == 1:
        base = 78
        label = "one_reply"
    elif comments == 2:
        base = 62
        label = "thin_thread"
    elif comments <= 5:
        base = 40
        label = "light_discussion"
    else:
        base = 15
        label = "active_thread"

    # Freshness boost (last 14 days best)
    age_days = None
    if created_utc:
        age_days = max(0.0, (time.time() - float(created_utc)) / 86400.0)
        if age_days <= 2:
            base += 8
        elif age_days <= 7:
            base += 5
        elif age_days <= 30:
            base += 2
        elif age_days > 180:
            base -= 20

    # Demand language boost
    demand_hits = sum(
        1
        for w in (
            "looking for", "need", "recommend", "anyone know", "hiring",
            "struggling", "help with", "where can i", "how do i find",
            "seeking", "in the market",
        )
        if w in text
    )
    base += min(12, demand_hits * 4)

    score = max(0, min(100, base))
    return {
        "silence_score": score,
        "silence_label": label,
        "num_comments": comments,
        "age_days": round(age_days, 1) if age_days is not None else None,
        "is_unanswered": comments <= 2 and score >= 55,
    }


def is_demand_text(text: str) -> bool:
    t = (text or "").lower()
    keys = (
        "looking for", "need a", "need an", "recommend", "anyone know",
        "hiring", "struggling", "help with", "where can i", "how do i",
        "seeking", "suggestions", "who should i", "best way to",
    )
    return any(k in t for k in keys)
