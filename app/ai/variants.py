"""Outreach variants scored by expected reply value."""

from __future__ import annotations

import re
from typing import Any

from app.ai.engine import ai_available, ai_mode, complete_json
from app.ai.intel import analyze_ask
from app.ai.nlp import clip

SYSTEM = (
    "You write short, human outreach that leads with genuine help. "
    "No hype, no emojis, no 'hope this helps'. Vary the angle across variants."
)


def generate_variants(
    lead: dict[str, Any],
    offer_info: dict[str, Any] | None = None,
    *,
    n: int = 4,
) -> dict[str, Any]:
    offer_info = offer_info or {}
    quote = clip(lead.get("ask_quote") or lead.get("evidence") or "", 400)
    if not quote:
        return {"variants": [], "error": "No ask text.", "source": ai_mode()}

    intel = analyze_ask(lead)
    if ai_available():
        gen = _generative(lead, offer_info, quote, intel, n)
        if gen:
            return gen
    return _heuristic(lead, offer_info, quote, intel, n)


def _generative(
    lead: dict[str, Any],
    offer_info: dict[str, Any],
    quote: str,
    intel: dict[str, Any],
    n: int,
) -> dict[str, Any] | None:
    prompt = (
        f"ASK:\n\"\"\"{quote}\"\"\"\n"
        f"Intent={intel['intent']} stage={intel['buying_stage']} "
        f"urgency={intel['urgency_label']} sentiment={intel['sentiment_label']}\n"
        f"My offer (context only): {offer_info.get('offer') or 'general help'}\n\n"
        f"Write {n} different outreach variants as JSON:\n"
        '{"variants":[{"angle":"help-first|proof-first|diagnostic|public-first",'
        '"channel":"public_reply|dm|email",'
        '"subject":"optional short subject",'
        '"body":"<=90 words, answers them first",'
        '"why_it_works":"one sentence"}]}\n'
        "Each variant MUST use a different angle. Cite a fragment of their ask."
    )
    data = complete_json(prompt, system=SYSTEM, max_tokens=1800, temperature=0.55)
    if not data or not data.get("variants"):
        return None
    variants = []
    for i, v in enumerate(data["variants"][:n]):
        if not isinstance(v, dict) or not v.get("body"):
            continue
        body = str(v.get("body") or "").strip()
        variants.append({
            "id": i + 1,
            "angle": str(v.get("angle") or "help-first"),
            "channel": str(v.get("channel") or "dm"),
            "subject": str(v.get("subject") or ""),
            "body": body,
            "why_it_works": str(v.get("why_it_works") or ""),
            "ev_score": _ev(intel, str(v.get("angle") or ""), body),
        })
    variants.sort(key=lambda v: -v["ev_score"])
    return {"variants": variants, "intel": intel, "source": ai_mode(), "error": ""}


def _heuristic(
    lead: dict[str, Any],
    offer_info: dict[str, Any],
    quote: str,
    intel: dict[str, Any],
    n: int,
) -> dict[str, Any]:
    frag = clip(quote, 70)
    name = lead.get("username") or "there"
    offer = clip(offer_info.get("offer") or "this", 60)
    templates = [
        {
            "angle": "help-first",
            "channel": "public_reply",
            "subject": "",
            "body": (
                f"On \"{frag}\" — the part that usually decides this is narrowing "
                f"to one measurable outcome first. Happy to share the 4-step checklist "
                f"I use before anyone spends money."
            ),
            "why_it_works": "Gives value publicly; builds reciprocity before any pitch.",
        },
        {
            "angle": "diagnostic",
            "channel": "dm",
            "subject": f"Quick take on your {intel['intent']} ask",
            "body": (
                f"Hey {name} — saw your post about \"{frag}\". "
                f"Two clarifying questions before I suggest anything: "
                f"(1) what's the deadline, (2) what's already been tried? "
                f"If useful I can send a one-page diagnostic."
            ),
            "why_it_works": "Questions lower resistance and qualify stage without pitching.",
        },
        {
            "angle": "proof-first",
            "channel": "email",
            "subject": f"Re: {frag[:40]}",
            "body": (
                f"Saw you were stuck on \"{frag}\". "
                f"Last time I solved a similar {intel['intent']} problem the unlock was "
                f"a tiny reversible test — not a big commitment. "
                f"I can walk you through that test if you want it."
            ),
            "why_it_works": "Proof + reversible ask beats feature lists for decision-stage buyers.",
        },
        {
            "angle": "public-first",
            "channel": "public_reply",
            "subject": "",
            "body": (
                f"Three constraints that kill most {intel['intent']} attempts: "
                f"unclear outcome, no kill-criteria, no timebox. "
                f"Write those three down before choosing {offer}."
            ),
            "why_it_works": "Teaches in public; positions you as the calm expert.",
        },
    ]
    variants = []
    for i, t in enumerate(templates[:n]):
        variants.append({
            "id": i + 1,
            **t,
            "ev_score": _ev(intel, t["angle"], t["body"]),
        })
    variants.sort(key=lambda v: -v["ev_score"])
    return {
        "variants": variants,
        "intel": intel,
        "source": "heuristic",
        "error": "",
        "note": "Add an OpenAI/Anthropic key for tailored generative variants.",
    }


def _ev(intel: dict[str, Any], angle: str, body: str) -> int:
    """Expected-value score blending reply odds with angle fitness."""
    base = int(intel.get("reply_odds") or 40)
    stage = intel.get("buying_stage") or "awareness"
    intent = intel.get("intent") or "howto"
    boost = 0
    if angle == "help-first" and stage in ("awareness", "consideration"):
        boost += 12
    if angle == "proof-first" and stage == "decision":
        boost += 15
    if angle == "diagnostic" and intent in ("hire", "switch", "debug"):
        boost += 10
    if angle == "public-first" and int(intel.get("urgency") or 0) < 40:
        boost += 8
    # Penalize length / hype
    words = len(body.split())
    if words > 100:
        boost -= 10
    if re.search(r"\b(synergy|game-?changer|crush|amazing)\b", body, re.I):
        boost -= 15
    return int(max(0, min(100, base + boost)))
