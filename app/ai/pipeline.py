"""Full intelligence pipeline — one call, every advanced AI layer.

Senior pattern: a single orchestrator that fans out into specialized modules
and returns a cockpit-ready payload the UI can render without N round trips.
"""

from __future__ import annotations

from typing import Any

from app.ai.contagion import contagion_rank
from app.ai.dialect import dialect_gap
from app.ai.engine import ai_mode
from app.ai.forecast import forecast_demand
from app.ai.graph import build_demand_graph
from app.ai.icp import discover_icp
from app.ai.integrity import verify_brief_pains
from app.ai.intel import analyze_many
from app.ai.match import match_summary, rank_asks
from app.ai.memory import retrieve_cases, training_signal
from app.ai.moat import moat_board
from app.ai.personas import infer_personas
from app.ai.saturation import saturation_map
from app.ai.solutions import solve_ask
from app.ai.stress import stress_test
from app.ai.synthesis import cluster_asks, compute_signal, demand_brief
from app.ai.vacuum import analyze_vacuum


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
    brief = demand_brief(leads, offer_info)

    # Novel white-space layers
    moat = moat_board(leads, limit=10)
    vacuum = analyze_vacuum(leads)
    saturation = saturation_map(leads)
    contagion = contagion_rank(leads, limit=8)
    dialect = dialect_gap(offer, leads) if offer else {"gap_score": 0, "label": "n/a", "insight": "Enter an offer to measure dialect gap."}
    icp = discover_icp(leads)
    integrity = verify_brief_pains(brief, leads)
    stress = stress_test(offer, leads) if offer else {"attacks": [], "survive_score": 0, "verdict": "Enter an offer to stress-test."}

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
        "moat": moat,
        "vacuum": vacuum,
        "saturation": saturation,
        "contagion": contagion,
        "dialect": dialect,
        "icp": icp,
        "integrity": integrity,
        "stress": stress,
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
            # white-space (not in DemandHunter / Matchstick / LeadIntent)
            "first_responder_moat",
            "competitor_vacuum",
            "do_nothing_share",
            "blue_ocean_saturation",
            "demand_contagion",
            "dialect_gap",
            "icp_autodiscovery",
            "evidence_integrity",
            "adversarial_stress_test",
            "counterfactual_demand",
        ],
    }


def solve_with_memory(
    lead: dict[str, Any],
    corpus: list[dict[str, Any]],
    offer_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Answer Engine augmented with nearest past wins + ask intelligence + moat."""
    from app.ai.intel import analyze_ask
    from app.ai.moat import first_responder_moat

    solution = solve_ask(lead, offer_info)
    intel = analyze_ask(lead)
    cases = retrieve_cases(lead, corpus, limit=4)
    moat = first_responder_moat(lead, corpus)

    solution["intel"] = intel
    solution["moat"] = moat
    solution["similar_cases"] = cases.get("cases") or []
    solution["memory_insight"] = cases.get("insight") or ""
    if cases.get("patterns"):
        solution["learned_patterns"] = cases["patterns"]

    near_win = next(
        (c for c in (cases.get("cases") or []) if c.get("polarity") == "win" and c["similarity"] >= 40),
        None,
    )
    if near_win and not solution.get("error"):
        solution["confidence"] = min(100, int(solution.get("confidence") or 0) + 8)
        tip = f" Similar win (sim {near_win['similarity']}%): “{near_win['quote'][:80]}”."
        if tip not in (solution.get("helpful_note") or ""):
            solution["helpful_note"] = ((solution.get("helpful_note") or "") + tip).strip()

    if moat.get("urgency") == "closing_fast" and solution.get("helpful_note"):
        solution["helpful_note"] = (
            f"[Moat ~{moat['moat_hours']}h] " + solution["helpful_note"]
        )

    return solution
