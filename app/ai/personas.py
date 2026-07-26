"""Intent-stage personas and objection mining."""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any

from app.ai.intel import analyze_ask
from app.ai.nlp import bag, clip, tokenize

OBJECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("budget", re.compile(r"\b(budget|expensive|costly|afford|cheap|pricing|pricey|too much)\b", re.I)),
    ("trust", re.compile(r"\b(scam|trust|reliable|legit|reputable|review|testimonial|proven)\b", re.I)),
    ("time", re.compile(r"\b(no time|too busy|time[- ]consuming|takes forever|slow|bandwidth)\b", re.I)),
    ("complexity", re.compile(r"\b(complicated|complex|steep learning|hard to|confusing|overwhelming)\b", re.I)),
    ("switching_cost", re.compile(r"\b(migrate|migration|switch|locked in|already using|current (tool|vendor|agency))\b", re.I)),
    ("risk", re.compile(r"\b(risk|worried|concern|what if|fail|guarantee|refund)\b", re.I)),
    ("diy", re.compile(r"\b(myself|diy|in[- ]house|on my own|learn to|self[- ]serve)\b", re.I)),
]


def infer_personas(leads: list[dict[str, Any]], *, max_personas: int = 5) -> dict[str, Any]:
    if not leads:
        return {"personas": [], "objections": [], "source": "heuristic"}

    buckets: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    intel_cache: dict[str, dict[str, Any]] = {}
    for lead in leads:
        intel = analyze_ask(lead)
        key = (intel["intent"], intel["buying_stage"])
        buckets[key].append(lead)
        intel_cache[lead.get("ask_id") or id(lead)] = intel  # type: ignore[index]

    personas: list[dict[str, Any]] = []
    for (intent, stage), members in sorted(buckets.items(), key=lambda kv: -len(kv[1])):
        if not members:
            continue
        vocab = Counter()
        urgencies = []
        contactable = 0
        for m in members:
            vocab.update(tokenize(_text(m)))
            intel = analyze_ask(m)
            urgencies.append(intel["urgency"])
            if m.get("email") or m.get("phone"):
                contactable += 1
        top_words = [w for w, _ in vocab.most_common(6)]
        name = _persona_name(intent, stage, top_words)
        personas.append({
            "name": name,
            "intent": intent,
            "buying_stage": stage,
            "count": len(members),
            "share": round(100 * len(members) / len(leads), 1),
            "avg_urgency": int(sum(urgencies) / len(urgencies)) if urgencies else 0,
            "contactable": contactable,
            "vocabulary": top_words,
            "example": clip(
                (members[0].get("ask_quote") or members[0].get("evidence") or ""), 200
            ),
            "how_to_win": _how_to_win(intent, stage),
        })
        if len(personas) >= max_personas:
            break

    objections = mine_objections(leads)
    return {
        "personas": personas,
        "objections": objections,
        "ask_count": len(leads),
        "source": "heuristic",
    }


def mine_objections(leads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    examples: dict[str, str] = {}
    for lead in leads:
        text = _text(lead)
        for label, pattern in OBJECTION_PATTERNS:
            if pattern.search(text):
                counts[label] += 1
                if label not in examples:
                    examples[label] = clip(
                        lead.get("ask_quote") or lead.get("evidence") or "", 160
                    )
    total = len(leads) or 1
    out = []
    for label, c in counts.most_common():
        out.append({
            "objection": label,
            "count": c,
            "share": round(100 * c / total, 1),
            "example": examples.get(label, ""),
            "counter": _counter_move(label),
        })
    return out


def _persona_name(intent: str, stage: str, words: list[str]) -> str:
    intent_n = {
        "hire": "Buyer",
        "recommend": "Comparer",
        "debug": "Fixer",
        "howto": "Learner",
        "price": "Budgeteer",
        "switch": "Switcher",
    }.get(intent, "Asker")
    stage_n = {
        "decision": "ready-to-act",
        "consideration": "weighing-options",
        "awareness": "just-exploring",
        "post_purchase": "already-buying",
    }.get(stage, stage)
    domain = words[0] if words else "general"
    return f"The {domain} {intent_n} ({stage_n})"


def _how_to_win(intent: str, stage: str) -> str:
    playbook = {
        ("hire", "decision"): "Lead with a scoped outcome + a tiny paid trial. Skip the pitch deck.",
        ("hire", "consideration"): "Send one comparable result with a metric. Offer a 20-min diagnostic.",
        ("recommend", "consideration"): "Give a 3-option framework with hard constraints, not a single pick.",
        ("debug", "awareness"): "Reproduce their error first. Publish the fix publicly before DMing.",
        ("howto", "awareness"): "Ship a checklist they can finish today. Soft CTA at the end only.",
        ("price", "decision"): "Show price bands tied to outcomes, not features. Offer a guarantee.",
        ("switch", "consideration"): "Map their migration cost. Offer to own the cutover risk.",
    }
    return playbook.get((intent, stage)) or playbook.get((intent, "awareness")) or (
        "Answer their question publicly with something useful before you pitch."
    )


def _counter_move(objection: str) -> str:
    return {
        "budget": "Lead with ROI math or a smaller scoped package, not a discount.",
        "trust": "Cite a specific comparable result + offer a reversible first step.",
        "time": "Reduce the ask to a 15-minute action with a clear done-state.",
        "complexity": "Replace jargon with a 3-step checklist and one screenshot.",
        "switching_cost": "Own the migration plan; price the cutover as a separate line.",
        "risk": "Offer a guarantee, pilot, or kill-criteria they control.",
        "diy": "Teach the first win free, then sell the boring remaining 80%.",
    }.get(objection, "Address it in the first sentence of your reply.")


def _text(lead: dict[str, Any]) -> str:
    return " ".join(
        str(lead.get(k) or "")
        for k in ("ask_quote", "evidence", "what_they_do", "site_title", "context")
    )
