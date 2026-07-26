"""Evidence-locked first-responder drafts."""

from __future__ import annotations

import re
from typing import Any


def build_drafts(lead: dict[str, Any], offer_info: dict[str, Any]) -> dict[str, str]:
    """
    Every draft must include the ask quote. No quote → empty drafts.
    Uses OpenAI/Anthropic to polish when API keys are present.
    """
    quote = (lead.get("ask_quote") or lead.get("evidence") or "").strip()
    if not quote:
        return {
            "public_reply": "",
            "dm_or_email": "",
            "call_opener": "",
            "sms": "",
        }

    short_quote = _clip(quote, 160)
    offer = (offer_info.get("offer") or "what I help with").strip()
    niche = (offer_info.get("niche") or "this").strip()
    name = lead.get("full_name") or lead.get("username") or "there"
    if name.startswith("u/"):
        name = name[2:]
    site = lead.get("site_title") or lead.get("what_they_do") or ""
    context_bit = f" ({_clip(site, 80)})" if site else ""

    public_reply = (
        f"Hey — saw this and figured I'd answer directly.\n\n"
        f"On \"{short_quote}\": {_helpful_angle(offer, niche)}\n\n"
        f"If useful, happy to share the exact playbook I use for {niche}. "
        f"No pitch needed unless you want it."
    )

    dm = (
        f"Hey {name}{context_bit},\n\n"
        f"You posted: \"{short_quote}\"\n\n"
        f"I help with: {offer}.\n\n"
        f"Quick take: {_helpful_angle(offer, niche)}\n\n"
        f"If you want, I can show you how I'd solve that in 10 minutes — "
        f"or I'll just send the steps async. Your call.\n\n"
        f"— sent via Panoptes Demand Radar"
    )

    call = (
        f"Hey {name}, this is a quick call — you posted about "
        f"\"{_clip(short_quote, 90)}\". "
        f"I help {niche} with {_clip(offer, 70)}. "
        f"Got 30 seconds for the short version?"
    )

    sms = (
        f"Hey {name} — saw your post about \"{_clip(short_quote, 60)}\". "
        f"I do {_clip(offer, 50)}. Want the quick fix or a 10-min walkthrough?"
    )

    drafts = {
        "public_reply": public_reply,
        "dm_or_email": dm,
        "call_opener": call,
        "sms": sms,
    }

    try:
        from app.providers.llm import llm_available, polish_drafts
        if llm_available():
            drafts = polish_drafts(lead, offer_info, drafts)
            drafts["draft_source"] = "llm"
        else:
            drafts["draft_source"] = "template"
    except Exception:
        drafts["draft_source"] = "template"

    return drafts


def _helpful_angle(offer: str, niche: str) -> str:
    o = offer.lower()
    if "appointment" in o or "setter" in o or "book" in o:
        return (
            f"most {niche} lose deals from inconsistent follow-up, not from bad offers. "
            f"A simple daily outbound + booking cadence usually fixes it in 1–2 weeks."
        )
    if "lead" in o:
        return (
            f"the bottleneck is usually offer clarity + channel fit, not just more volume. "
            f"I'd tighten the ICP and run one high-intent channel hard first."
        )
    return (
        f"I'd start by clarifying the exact outcome you want, then reverse into "
        f"the fastest channel that already has demand for {niche}."
    )


def _clip(text: str, n: int) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"
