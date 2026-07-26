"""Cascade value of answering a bridge ask."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from app.ai.graph import build_demand_graph
from app.ai.nlp import clip, tokenize


def contagion_rank(leads: list[dict[str, Any]], *, limit: int = 12) -> dict[str, Any]:
    if not leads:
        return {"ranked": [], "insight": "No asks.", "graph_hubs": []}

    graph = build_demand_graph(leads)
    hub_set = set(graph.get("hubs") or [])
    bridge_set = set(graph.get("bridges") or [])
    # Build term → ask adjacency
    term_asks: dict[str, list[int]] = defaultdict(list)
    ask_terms: list[set[str]] = []
    for i, lead in enumerate(leads):
        terms = set(tokenize(_text(lead)))
        ask_terms.append(terms)
        for t in terms:
            term_asks[t].append(i)

    # Cascade value of answering ask i:
    #   silence × (hub overlap + bridge overlap + neighbor ask count via shared terms)
    ranked = []
    for i, lead in enumerate(leads):
        terms = ask_terms[i]
        hub_hit = len(terms & hub_set)
        bridge_hit = len(terms & bridge_set)
        neighbors = set()
        for t in terms:
            for j in term_asks[t]:
                if j != i:
                    neighbors.add(j)
        # Unique neighboring asks reachable in 1 hop through shared vocabulary
        reach = len(neighbors)
        silence = int(lead.get("silence_score") or 0)
        cascade = (
            0.35 * silence
            + 0.25 * min(100, reach * 8)
            + 0.25 * min(100, hub_hit * 25)
            + 0.15 * min(100, bridge_hit * 30)
        )
        ranked.append({
            "ask_id": lead.get("ask_id") or "",
            "username": lead.get("username") or "",
            "quote": clip(lead.get("ask_quote") or lead.get("evidence") or "", 180),
            "cascade_score": int(round(cascade)),
            "reach": reach,
            "hub_hits": hub_hit,
            "bridge_hits": bridge_hit,
            "silence_score": silence,
            "why": (
                f"Answering this reaches ~{reach} adjacent asks via shared language"
                + (f"; sits on hubs {', '.join(sorted(terms & hub_set)[:3])}" if hub_hit else "")
                + "."
            ),
        })

    ranked.sort(key=lambda r: -r["cascade_score"])
    top = ranked[:limit]
    insight = (
        f"Top contagion ask reaches ~{top[0]['reach']} neighbors "
        f"(cascade {top[0]['cascade_score']}). "
        "Answer bridge/hub asks first — authority spills into adjacent themes."
        if top else "No contagion signal."
    )
    return {
        "ranked": top,
        "graph_hubs": graph.get("hubs") or [],
        "insight": insight,
    }


def _text(lead: dict[str, Any]) -> str:
    return " ".join(str(lead.get(k) or "") for k in ("ask_quote", "evidence", "what_they_do"))
