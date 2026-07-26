"""Keyword co-occurrence graph with PageRank hubs."""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Any

from app.ai.nlp import clip, tokenize


def build_demand_graph(
    leads: list[dict[str, Any]],
    *,
    max_nodes: int = 40,
    max_edges: int = 60,
) -> dict[str, Any]:
    if not leads:
        return {"nodes": [], "edges": [], "hubs": [], "bridges": []}

    # Per-doc unique terms (cap per ask so long posts don't drown short ones)
    docs: list[set[str]] = []
    for lead in leads:
        toks = tokenize(_text(lead))
        # Keep the most frequent local terms
        counts = Counter(toks)
        docs.append({t for t, _ in counts.most_common(12)})

    term_df: Counter[str] = Counter()
    for d in docs:
        term_df.update(d)

    # Keep top vocabulary by document frequency
    vocab = {t for t, _ in term_df.most_common(max_nodes)}

    # Co-occurrence
    edge_w: Counter[tuple[str, str]] = Counter()
    for d in docs:
        terms = sorted(t for t in d if t in vocab)
        for i, a in enumerate(terms):
            for b in terms[i + 1 :]:
                edge_w[(a, b)] += 1

    # Drop weak edges
    edges_raw = [(a, b, w) for (a, b), w in edge_w.items() if w >= 2]
    edges_raw.sort(key=lambda e: -e[2])
    edges_raw = edges_raw[:max_edges]

    # Adjacency for PageRank
    adj: dict[str, list[tuple[str, float]]] = defaultdict(list)
    nodes_used: set[str] = set()
    for a, b, w in edges_raw:
        adj[a].append((b, float(w)))
        adj[b].append((a, float(w)))
        nodes_used.add(a)
        nodes_used.add(b)

    # If graph is empty, fall back to DF hubs
    if not nodes_used:
        hubs = [{"id": t, "weight": c, "centrality": 0.0} for t, c in term_df.most_common(8)]
        return {"nodes": hubs, "edges": [], "hubs": [h["id"] for h in hubs[:5]], "bridges": []}

    ranks = _pagerank(adj, damping=0.85, iters=25)

    nodes = [
        {
            "id": t,
            "weight": term_df[t],
            "centrality": round(ranks.get(t, 0.0), 4),
        }
        for t in nodes_used
    ]
    nodes.sort(key=lambda n: (-n["centrality"], -n["weight"]))

    edges = [
        {"source": a, "target": b, "weight": w}
        for a, b, w in edges_raw
        if a in nodes_used and b in nodes_used
    ]

    # Hubs = high centrality. Bridges = high betweenness approximation
    # (degree × diversity of neighbors' communities via DF span).
    hubs = [n["id"] for n in nodes[:6]]
    bridges = _bridge_terms(adj, ranks, term_df)[:5]

    return {
        "nodes": nodes[:max_nodes],
        "edges": edges,
        "hubs": hubs,
        "bridges": bridges,
        "ask_count": len(leads),
        "insight": _insight(hubs, bridges, leads),
    }


def _pagerank(
    adj: dict[str, list[tuple[str, float]]],
    *,
    damping: float = 0.85,
    iters: int = 25,
) -> dict[str, float]:
    nodes = list(adj.keys())
    if not nodes:
        return {}
    n = len(nodes)
    rank = {t: 1.0 / n for t in nodes}
    for _ in range(iters):
        nxt = {t: (1 - damping) / n for t in nodes}
        for t in nodes:
            neighbors = adj[t]
            if not neighbors:
                # Distribute to all (dangling)
                share = damping * rank[t] / n
                for u in nodes:
                    nxt[u] += share
                continue
            total_w = sum(w for _, w in neighbors) or 1.0
            for u, w in neighbors:
                nxt[u] += damping * rank[t] * (w / total_w)
        rank = nxt
    # Normalize
    s = sum(rank.values()) or 1.0
    return {k: v / s for k, v in rank.items()}


def _bridge_terms(
    adj: dict[str, list[tuple[str, float]]],
    ranks: dict[str, float],
    df: Counter[str],
) -> list[str]:
    """Approximate bridges: high degree but not the absolute hub — they connect clusters."""
    scored: list[tuple[float, str]] = []
    for t, neighbors in adj.items():
        deg = len(neighbors)
        if deg < 2:
            continue
        # Neighbor DF variance proxy — diverse neighbors ⇒ bridge
        neigh_df = [df[u] for u, _ in neighbors]
        mean = sum(neigh_df) / len(neigh_df)
        var = sum((x - mean) ** 2 for x in neigh_df) / len(neigh_df)
        score = math.sqrt(var) * math.log(1 + deg) * (0.5 + ranks.get(t, 0))
        scored.append((score, t))
    scored.sort(reverse=True)
    return [t for _, t in scored]


def _insight(hubs: list[str], bridges: list[str], leads: list[dict[str, Any]]) -> str:
    if not hubs:
        return "Not enough co-occurrence yet to map demand structure."
    hub_s = ", ".join(hubs[:3])
    if bridges:
        return (
            f"Structural demand hubs: {hub_s}. "
            f"Bridge terms linking themes: {', '.join(bridges[:3])} — "
            f"these are the words that connect otherwise separate buyer pains across {len(leads)} asks."
        )
    return f"Structural demand hubs across {len(leads)} asks: {hub_s}."


def _text(lead: dict[str, Any]) -> str:
    return " ".join(
        str(lead.get(k) or "")
        for k in ("ask_quote", "evidence", "what_they_do", "site_title")
    )
