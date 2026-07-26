"""Adversarial Offer Stress Test — attack your offer with synthetic buyer objections.

Generative-agent research is emerging; almost no demand tool stress-tests an
offer against adversarial personas grounded in *your real silent asks*.
Free path uses mined objections + persona templates; LLM path writes sharper attacks.
"""

from __future__ import annotations

from typing import Any

from app.ai.engine import ai_available, ai_mode, complete_json
from app.ai.personas import infer_personas, mine_objections

SYSTEM = (
    "You are a ruthless but fair buyer. Attack the offer with specific objections "
    "grounded in the real asks provided. Never invent fake statistics."
)


def stress_test(offer: str, leads: list[dict[str, Any]]) -> dict[str, Any]:
    offer = (offer or "").strip()
    if not offer:
        return {"error": "Provide an offer to stress-test.", "attacks": []}

    personas = infer_personas(leads)
    objections = mine_objections(leads) or [
        {"objection": "budget", "counter": "", "share": 0, "count": 0, "example": ""},
        {"objection": "trust", "counter": "", "share": 0, "count": 0, "example": ""},
        {"objection": "switching_cost", "counter": "", "share": 0, "count": 0, "example": ""},
    ]

    if ai_available() and leads:
        gen = _generative(offer, leads, personas, objections)
        if gen:
            return gen
    return _heuristic(offer, personas, objections)


def _generative(offer, leads, personas, objections) -> dict[str, Any] | None:
    sample = [
        (l.get("ask_quote") or l.get("evidence") or "")[:180]
        for l in leads[:12]
    ]
    prompt = (
        f"OFFER UNDER ATTACK: {offer}\n\n"
        f"REAL ASKS:\n" + "\n".join(f"- {s}" for s in sample if s) + "\n\n"
        f"KNOWN OBJECTION TYPES: {[o['objection'] for o in objections]}\n"
        f"PERSONAS: {[p['name'] for p in (personas.get('personas') or [])[:4]]}\n\n"
        "Return JSON: {\"attacks\":[{\"persona\":str,\"objection\":str,"
        "\"attack\":str,\"severity\":int,\"defense\":str}],"
        "\"survive_score\":0-100,\"verdict\":str}\n"
        "Write 4 sharp attacks. severity 1-10. defense = one concrete counter."
    )
    data = complete_json(prompt, system=SYSTEM, max_tokens=1600, temperature=0.5)
    if not data or not data.get("attacks"):
        return None
    attacks = []
    for a in data["attacks"][:5]:
        if not isinstance(a, dict):
            continue
        attacks.append({
            "persona": str(a.get("persona") or "Buyer")[:80],
            "objection": str(a.get("objection") or "")[:40],
            "attack": str(a.get("attack") or "")[:300],
            "severity": int(a.get("severity") or 5),
            "defense": str(a.get("defense") or "")[:240],
        })
    return {
        "attacks": attacks,
        "survive_score": int(data.get("survive_score") or 50),
        "verdict": str(data.get("verdict") or "")[:200],
        "source": ai_mode(),
        "error": "",
    }


def _heuristic(offer: str, personas: dict, objections: list) -> dict[str, Any]:
    attacks = []
    templates = {
        "budget": (
            "This sounds expensive and I already have a spreadsheet that 'works'. "
            "Show me the ROI math in one screen or I'm out."
        ),
        "trust": (
            "I've been burned by agencies that overpromised. "
            "Why should I believe you over the last three I tried?"
        ),
        "switching_cost": (
            "Migration will eat a month. Unless you own the cutover risk, we stay put."
        ),
        "time": (
            "I don't have bandwidth for onboarding. If this takes more than an hour "
            "in week one, it dies."
        ),
        "complexity": (
            "Too many moving parts. Give me a 3-step version or I'll DIY."
        ),
        "risk": (
            "What if this fails? I need a kill-switch and a refund path before I sign."
        ),
        "diy": (
            "I can learn this myself for free. Why pay you instead of watching a tutorial?"
        ),
    }
    persona_names = [p["name"] for p in (personas.get("personas") or [])] or ["Skeptical buyer"]
    for i, obj in enumerate(objections[:5] or [{"objection": k} for k in list(templates)[:4]]):
        label = obj.get("objection") or "trust"
        attacks.append({
            "persona": persona_names[i % len(persona_names)],
            "objection": label,
            "attack": templates.get(label, templates["trust"]),
            "severity": min(10, 5 + int((obj.get("share") or 10) / 15)),
            "defense": obj.get("counter") or _default_defense(label),
        })

    # Survive score: inverse of average severity, boosted if offer has concrete nouns
    avg_sev = sum(a["severity"] for a in attacks) / max(1, len(attacks))
    concrete = sum(1 for w in offer.lower().split() if w not in {"i", "a", "the", "and", "for", "to"})
    survive = int(max(15, min(90, 100 - avg_sev * 8 + min(15, concrete))))

    return {
        "attacks": attacks,
        "survive_score": survive,
        "verdict": (
            f"Offer survives at {survive}/100 under adversarial fire. "
            "Tighten defenses on the highest-severity objections before scaling outreach."
        ),
        "source": "heuristic",
        "error": "",
        "note": "Add an OpenAI/Anthropic key for sharper attacks grounded in your exact asks.",
    }


def _default_defense(label: str) -> str:
    return {
        "budget": "Lead with a scoped pilot price tied to one metric.",
        "trust": "Cite one comparable result with a number + offer a reversible first step.",
        "switching_cost": "Publish a migration checklist and own the cutover as a line item.",
        "time": "Ship a 15-minute first win with a clear done-state.",
        "complexity": "Cut the pitch to three steps and one screenshot.",
        "risk": "Add an explicit kill-criteria and guarantee window.",
        "diy": "Teach the first win free; sell the remaining 80% of boring work.",
    }.get(label, "Answer the objection in the first sentence of every reply.")
