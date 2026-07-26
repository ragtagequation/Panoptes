"""Blue-Ocean / Saturation scoring per demand theme.

A theme is 'blue ocean' when asks are high-silence AND buyers rarely name
alternatives. It's 'saturated' when similar threads already have replies or
vendors are constantly compared. Most tools stop at 'demand exists'.
"""

from __future__ import annotations

import re
from typing import Any

from app.ai.nlp import clip
from app.ai.synthesis import cluster_asks
from app.ai.vacuum import FAIL_KNOWN, VENDORISH

COMPARE_PAT = re.compile(r"\b(vs\.?|versus|alternative|instead of|compared to|better than)\b", re.I)


def saturation_map(leads: list[dict[str, Any]]) -> dict[str, Any]:
    clusters = cluster_asks(leads, max_clusters=8)
    if not clusters:
        return {"themes": [], "blue_ocean": [], "saturated": [], "insight": "No themes yet."}

    themes = []
    for cl in clusters:
        # Recover member leads via example usernames is lossy — rescore using
        # keyword overlap against the full corpus instead.
        members = _members_for_theme(cl, leads)
        if not members:
            members = leads[: max(1, cl["count"])]

        n = len(members)
        avg_sil = sum(int(l.get("num_comments") or 0) == 0 for l in members) / n
        avg_silence_score = sum(int(l.get("silence_score") or 0) for l in members) / n
        vendor_hits = sum(
            1 for l in members
            if FAIL_KNOWN.search(_text(l)) or VENDORISH.search(_text(l))
        )
        compare_hits = sum(1 for l in members if COMPARE_PAT.search(_text(l)))
        vendor_rate = vendor_hits / n
        compare_rate = compare_hits / n

        # Blue ocean: high silence, low vendor talk, low comparison
        # Saturated: low silence OR high vendor/compare density
        blue = 100 * (0.45 * avg_sil + 0.35 * (avg_silence_score / 100) + 0.20 * (1 - vendor_rate))
        sat = 100 * (0.40 * (1 - avg_sil) + 0.35 * vendor_rate + 0.25 * compare_rate)
        blue = int(round(max(0, min(100, blue))))
        sat = int(round(max(0, min(100, sat))))

        label = "blue_ocean" if blue >= 60 and sat < 45 else "saturated" if sat >= 55 else "contested"

        themes.append({
            "theme": cl["theme"],
            "count": cl["count"],
            "share": cl["share"],
            "blue_ocean_score": blue,
            "saturation_score": sat,
            "label": label,
            "zero_reply_rate": round(100 * avg_sil, 1),
            "vendor_mention_rate": round(100 * vendor_rate, 1),
            "example": cl["examples"][0]["quote"] if cl.get("examples") else "",
            "play": _play(label, cl["theme"]),
        })

    themes.sort(key=lambda t: -t["blue_ocean_score"])
    blue = [t for t in themes if t["label"] == "blue_ocean"]
    saturated = [t for t in themes if t["label"] == "saturated"]

    insight = (
        f"{len(blue)} blue-ocean theme(s) — high silence, few named alternatives. "
        f"{len(saturated)} saturated theme(s) — crowded comparisons or already-answered threads. "
        "Enter blue ocean first; in saturated themes, win on a sharp wedge only."
    )
    return {
        "themes": themes,
        "blue_ocean": blue,
        "saturated": saturated,
        "insight": insight,
    }


def _members_for_theme(cluster: dict[str, Any], leads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keys = set(cluster.get("keywords") or [])
    if not keys:
        return []
    out = []
    for lead in leads:
        toks = set(_text(lead).lower().replace("-", " ").split())
        # crude stem-ish: substring match on keywords
        hits = sum(1 for k in keys if any(k in t or t.startswith(k[:4]) for t in toks if len(t) > 3))
        if hits >= max(1, len(keys) // 3):
            out.append(lead)
    return out


def _play(label: str, theme: str) -> str:
    if label == "blue_ocean":
        return f"Own '{theme}' publicly — publish the checklist, then DM the silent askers."
    if label == "saturated":
        return f"Don't out-shout '{theme}'. Pick one underserved constraint and wedge there."
    return f"'{theme}' is contested — differentiate with proof + a reversible pilot."


def _text(lead: dict[str, Any]) -> str:
    return " ".join(str(lead.get(k) or "") for k in ("ask_quote", "evidence", "context"))
