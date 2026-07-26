"""Full intelligence pipeline — one call, every advanced AI layer.

Senior pattern: a single orchestrator that fans out into specialized modules
and returns a cockpit-ready payload the UI can render without N round trips.
"""

from __future__ import annotations

from typing import Any

from app.ai.engine import ai_mode
from app.ai.forecast import forecast_demand
from app.ai.graph import build_demand_graph
from app.ai.intel import analyze_many
from app.ai.match import match_summary, rank_asks
from app.ai.memory import retrieve_cases, training_signal
from app.ai.personas import infer_personas
from app.ai.synthesis import cluster_asks, compute_signal, demand_brief
from app.ai.solutions import solve_ask


def run_cockpit(
    leads: list[dict[str, Any]],
    offer_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Aggregate demand intelligence for the AI cockpit panel."""
    offer_info = offer_info or {}
    offer = offer_info.get("offer") or ""

    signal = compute_signal(leads)
    clusters = cluster_asks(leads)
    ranked = rank_asks(offer, leads, limit=20) if offer else []
    intel = analyze_many(leads)[:15]
    graph = build_demand_graph(leads)
    personas = infer_personas(leads)
    forecast = forecast_demand(leads)
    memory = training_signal(leads)

    # Lightweight brief without a second LLM call if we already have heuristic path
    brief = demand_brief(leads, offer_info)

    return {
        "source": ai_mode(),
        "stats": signal,
        "brief": {
            "verdict": brief.get("verdict"),
            "reasoning": brief.get("reasoning"),
            "demand_score": brief.get("demand_score"),
            "voice_of_customer": brief.get("voice_of_customer"),
            "top_pains": brief.get("top_pains"),
            "next_actions": brief.get("next_actions"),
            "riskiest_assumption": brief.get("riskiest_assumption"),
            "positioning": brief.get("positioning"),
        },
        "clusters": clusters,
        "ranked": ranked,
        "match": match_summary(ranked),
        "intel": intel,
        "graph": graph,
        "personas": personas.get("personas") or [],
        "objections": personas.get("objections") or [],
        "forecast": forecast,
        "memory": memory,
        "capabilities": [
            "answer_engine",
            "demand_verdict",
            "tfidf_clustering",
            "bm25_offer_match",
            "naive_bayes_intent",
            "urgency_sentiment",
            "buying_stage",
            "reply_odds",
            "pagerank_demand_graph",
            "persona_inference",
            "objection_mining",
            "ols_forecast",
            "ab_variants",
            "outcome_rag",
            "offer_doctor",
        ],
    }


def solve_with_memory(
    lead: dict[str, Any],
    corpus: list[dict[str, Any]],
    offer_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Answer Engine augmented with nearest past wins + ask intelligence."""
    from app.ai.intel import analyze_ask

    solution = solve_ask(lead, offer_info)
    intel = analyze_ask(lead)
    cases = retrieve_cases(lead, corpus, limit=4)

    # Enrich the solution packet
    solution["intel"] = intel
    solution["similar_cases"] = cases.get("cases") or []
    solution["memory_insight"] = cases.get("insight") or ""
    if cases.get("patterns"):
        solution["learned_patterns"] = cases["patterns"]

    # Boost confidence slightly when a near win exists
    near_win = next((c for c in (cases.get("cases") or []) if c.get("polarity") == "win" and c["similarity"] >= 40), None)
    if near_win and not solution.get("error"):
        solution["confidence"] = min(100, int(solution.get("confidence") or 0) + 8)
        if solution.get("assumption") == "" or "without a language model" in (solution.get("assumption") or ""):
            pass
        tip = f" Similar win (sim {near_win['similarity']}%): “{near_win['quote'][:80]}”."
        if tip not in (solution.get("helpful_note") or ""):
            solution["helpful_note"] = ((solution.get("helpful_note") or "") + tip).strip()

    return solution
