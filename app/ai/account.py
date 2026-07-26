"""Account intelligence — firmographics × technographics × ask intent."""

from __future__ import annotations

from collections import Counter
from typing import Any

from app.ai.engine import ai_available, ai_mode, complete_json
from app.ai.firmographics import extract_firmographics, firmographic_landscape
from app.ai.intel import analyze_ask
from app.ai.nlp import clip
from app.ai.technographics import extract_technographics, stack_gap, technographic_landscape

SYSTEM = (
    "You write concise account briefs for sales operators. "
    "Ground every claim in the supplied firmographic and technographic facts. "
    "No fluff, no invented tools."
)


def account_packet(lead: dict[str, Any], offer: str = "") -> dict[str, Any]:
    firm = extract_firmographics(lead)
    tech = extract_technographics(lead)
    intent = analyze_ask(lead)
    gap = stack_gap(offer, tech) if offer else {"wedge": "unknown", "note": "", "conflicts": [], "complements": [], "missing": []}

    tier = _tier(firm, tech, intent)
    fit = _offer_fit(offer, firm, tech, intent) if offer else 0

    packet = {
        "ask_id": lead.get("ask_id") or "",
        "username": lead.get("username") or "",
        "website": lead.get("website") or "",
        "firmographics": firm,
        "technographics": tech,
        "stack_gap": gap,
        "intent": intent.get("intent"),
        "buying_stage": intent.get("buying_stage"),
        "reply_odds": intent.get("reply_odds"),
        "account_tier": tier,
        "offer_fit": fit,
        "quote": clip(lead.get("ask_quote") or lead.get("evidence") or "", 160),
        "brief": "",
        "source": "heuristic",
    }
    packet["brief"] = _heuristic_brief(packet, offer)
    return packet


def account_landscape(leads: list[dict[str, Any]], offer: str = "") -> dict[str, Any]:
    packets = [account_packet(l, offer) for l in leads]
    packets.sort(key=lambda p: (-p["offer_fit"], -p["account_tier"]["score"]))
    firm_land = firmographic_landscape(leads)
    tech_land = technographic_landscape(leads)
    tiers = Counter(p["account_tier"]["label"] for p in packets)
    wedges = Counter(p["stack_gap"].get("wedge") for p in packets)

    return {
        "accounts": packets[:20],
        "firmographics": firm_land,
        "technographics": tech_land,
        "tier_mix": dict(tiers),
        "wedge_mix": dict(wedges),
        "top_fit": packets[0]["offer_fit"] if packets else 0,
        "insight": _landscape_insight(firm_land, tech_land, tiers, wedges),
    }


def account_brief_generative(lead: dict[str, Any], offer: str = "") -> dict[str, Any]:
    base = account_packet(lead, offer)
    if not ai_available():
        return base

    firm = base["firmographics"]
    tech = base["technographics"]
    prompt = (
        f"OFFER: {offer or 'unspecified'}\n"
        f"ASK: {base['quote']}\n"
        f"FIRM: industry={firm['industry']} size={firm['size_band']} org={firm['org_type']} "
        f"geo={firm['geo'].get('region')} revenue={firm.get('revenue_signal')}\n"
        f"TECH: {tech.get('by_category')} maturity={tech.get('maturity')}\n"
        f"WEDGE: {base['stack_gap']}\n"
        f"INTENT: {base['intent']} stage={base['buying_stage']} odds={base['reply_odds']}\n\n"
        "Return JSON with keys: "
        '{"brief":"<=70 words account brief",'
        '"angle":"one outreach angle",'
        '"landmine":"one thing not to say",'
        '"next_step":"one concrete next step"}'
    )
    data = complete_json(prompt, system=SYSTEM, max_tokens=700, temperature=0.35)
    if not data or not data.get("brief"):
        return base
    base["brief"] = str(data.get("brief") or "")[:500]
    base["angle"] = str(data.get("angle") or "")[:200]
    base["landmine"] = str(data.get("landmine") or "")[:200]
    base["next_step"] = str(data.get("next_step") or "")[:200]
    base["source"] = ai_mode()
    return base


def _tier(firm: dict, tech: dict, intent: dict) -> dict[str, Any]:
    score = 30
    size_w = {"enterprise": 25, "midmarket": 20, "smb": 14, "micro": 8, "solo": 4, "unknown": 0}
    score += size_w.get(firm.get("size_band"), 0)
    score += min(20, tech.get("stack_size", 0) * 4)
    if intent.get("buying_stage") == "decision":
        score += 15
    elif intent.get("buying_stage") == "consideration":
        score += 8
    if firm.get("revenue_signal"):
        score += 8
    if intent.get("intent") in ("hire", "switch", "price"):
        score += 10
    score = int(max(0, min(100, score)))
    label = "A" if score >= 70 else "B" if score >= 45 else "C"
    return {"score": score, "label": label}


def _offer_fit(offer: str, firm: dict, tech: dict, intent: dict) -> int:
    if not offer:
        return 0
    score = 20
    offer_l = offer.lower()
    industry = firm.get("industry") or ""
    if industry != "unknown" and industry.replace("_", " ") in offer_l:
        score += 25
    elif industry != "unknown":
        # soft relatedness
        related = {
            "dental": ["dental", "clinic", "appointment", "patient"],
            "healthcare": ["health", "clinic", "patient", "medical"],
            "agency": ["agency", "client", "lead", "appointment"],
            "saas": ["saas", "b2b", "pipeline", "outbound"],
            "ecommerce": ["store", "shopify", "ecommerce", "dtc"],
            "construction": ["roof", "contractor", "home service"],
        }
        if any(w in offer_l for w in related.get(industry, [])):
            score += 15

    gap = stack_gap(offer, tech)
    if gap["wedge"] == "fill_gap":
        score += 18
    elif gap["wedge"] == "displace":
        score += 10
    elif gap["wedge"] == "complement":
        score += 12

    score += min(20, int(intent.get("reply_odds") or 0) // 5)
    if intent.get("intent") in ("hire", "switch"):
        score += 10
    return int(max(0, min(100, score)))


def _heuristic_brief(packet: dict, offer: str) -> str:
    firm = packet["firmographics"]
    tech = packet["technographics"]
    tier = packet["account_tier"]
    parts = [
        f"Tier {tier['label']} ({tier['score']})",
        f"{firm['industry']}/{firm['size_band']}" if firm["industry"] != "unknown" else firm["size_band"],
    ]
    if tech["stack_size"]:
        products = [h["product"] for h in tech["products"][:3]]
        parts.append("stack " + ", ".join(products))
    else:
        parts.append("stack unknown")
    gap = packet["stack_gap"]
    if gap.get("note"):
        parts.append(gap["note"])
    if offer and packet["offer_fit"]:
        parts.append(f"offer-fit {packet['offer_fit']}")
    return " · ".join(parts)


def _landscape_insight(firm, tech, tiers, wedges) -> str:
    top_ind = firm["industries"][0]["name"] if firm.get("industries") else "mixed"
    top_tech = tech["top_products"][0]["name"] if tech.get("top_products") else "none detected"
    a_count = tiers.get("A", 0)
    return (
        f"Corpus leans {top_ind}; common stack signal: {top_tech}. "
        f"{a_count} tier-A accounts. "
        f"Wedges: {dict(wedges)}."
    )
