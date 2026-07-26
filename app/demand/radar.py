"""Demand Radar orchestration."""

from __future__ import annotations

import csv
import logging
import re
import time
from pathlib import Path
from typing import Any, Callable, Optional

from app.demand.asks import hunt_asks
from app.demand.deepen import deepen_lead
from app.demand.drafts import build_drafts
from app.demand.offers import compile_offer
from app.demand.store import filter_new_asks, upsert_leads
from app.discovery.contacts import enrich_lead_contacts
from app.scrapers.stealth import random_delay

logger = logging.getLogger(__name__)
ProgressCb = Optional[Callable[[str], None]]


def run_demand_radar(
    offer: str,
    *,
    niche: str = "",
    company: str = "",
    target: int = 25,
    max_comments: int = 2,
    min_silence: int = 55,
    require_contact: bool = False,
    only_new: bool = False,
    include_web: bool = True,
    scrape_sites: bool = True,
    deepen: bool = True,
    on_progress: ProgressCb = None,
) -> dict[str, Any]:
    """
    Full pipeline: compile offer -> hunt unanswered asks -> enrich -> deepen socials -> drafts.
    """
    def progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)
        logger.info(msg)

    compiled = compile_offer(offer, niche=niche, company=company)
    progress(f"Offer compiled -> {len(compiled['queries'])} demand queries")

    asks = hunt_asks(
        compiled["queries"],
        max_comments=max_comments,
        min_silence=min_silence,
        limit_per_query=35,
        include_web=include_web,
        on_progress=progress,
    )

    if only_new:
        before = len(asks)
        asks = filter_new_asks(asks)
        progress(f"Deduped seen asks: {before} -> {len(asks)} new")

    # Prefer unanswered reddit asks, then web
    asks.sort(
        key=lambda a: (
            0 if a.get("ask_source") == "reddit" else 1,
            -int(a.get("silence_score") or 0),
            a.get("age_days") if a.get("age_days") is not None else 999,
        )
    )

    enriched: list[dict[str, Any]] = []
    deepened_n = 0
    for i, ask in enumerate(asks, 1):
        if len(enriched) >= target * 3:  # over-fetch then filter
            break
        progress(f"Enriching ask {i}/{min(len(asks), target * 3)}: u/{ask.get('username')}")
        lead = dict(ask)
        # Use evidence as bio for contact harvest
        lead["bio"] = ask.get("ask_quote") or ""
        try:
            lead = enrich_lead_contacts(lead, scrape_site=scrape_sites and bool(lead.get("website")))
        except Exception as e:
            logger.debug("enrich failed: %s", e)

        if deepen:
            try:
                before_contact = bool(lead.get("email") or lead.get("phone"))
                lead = deepen_lead(lead, scrape_sites=scrape_sites)
                if lead.get("deepened_platforms"):
                    deepened_n += 1
                    progress(
                        f"  Deepened {', '.join(lead['deepened_platforms'])}"
                        + ("" if before_contact or not (lead.get("email") or lead.get("phone"))
                           else " -> found contact")
                    )
            except Exception as e:
                logger.debug("deepen failed: %s", e)

        drafts = build_drafts(lead, compiled)
        lead.update({
            "public_reply": drafts["public_reply"],
            "dm_or_email": drafts["dm_or_email"],
            "call_opener": drafts["call_opener"],
            "sms": drafts["sms"],
            "offer": compiled["offer"],
            "niche": compiled["niche"],
            "contactable": bool(lead.get("email") or lead.get("phone")),
            "complete_contact": bool(lead.get("email") and lead.get("phone")),
        })
        enriched.append(lead)
        random_delay(0.15, 0.4)

    # Rank: contactable unanswered first
    enriched.sort(
        key=lambda x: (
            0 if x.get("complete_contact") else 1,
            0 if x.get("contactable") else 1,
            0 if x.get("ask_source") == "reddit" else 1,
            -int(x.get("silence_score") or 0),
        )
    )

    if require_contact:
        final = [l for l in enriched if l.get("contactable")]
    else:
        # Keep mix but put contactable first; still return public-reply opportunities
        final = enriched

    final = final[:target]
    upsert_leads(final, offer=compiled["offer"])

    stats = {
        "total": len(final),
        "contactable": sum(1 for l in final if l.get("contactable")),
        "complete_contact": sum(1 for l in final if l.get("complete_contact")),
        "zero_replies": sum(1 for l in final if int(l.get("num_comments") or 0) == 0),
        "deepened": deepened_n,
        "avg_silence": int(sum(int(l.get("silence_score") or 0) for l in final) / len(final)) if final else 0,
    }
    progress(
        f"Radar done - {stats['total']} asks "
        f"({stats['contactable']} contactable, {stats['zero_replies']} zero-reply, "
        f"{stats['deepened']} deepened)"
    )

    return {
        "offer": compiled,
        "leads": final,
        "stats": stats,
    }


def save_radar_export(leads: list[dict[str, Any]], out_dir: Path, offer: str) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    slug = re.sub(r"[^a-z0-9]+", "_", (offer or "offer").lower()).strip("_")[:40] or "offer"
    files: dict[str, str] = {}

    fields = [
        "username", "platform", "silence_score", "silence_label", "num_comments", "age_days",
        "ask_quote", "ask_url", "email", "phone", "website", "what_they_do", "site_title",
        "contactable", "complete_contact", "deepened_platforms", "dm_or_email", "call_opener",
        "public_reply", "sms", "context", "query", "offer", "niche", "status", "outcome",
    ]
    name = f"radar_{slug}_{stamp}.csv"
    path = out_dir / name
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for lead in leads:
            w.writerow(lead)
    files["radar_csv"] = name

    # Instantly-ish export
    instantly = f"radar_{slug}_instantly_{stamp}.csv"
    with open(out_dir / instantly, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["email", "first_name", "companyName", "personalization", "website", "phone"],
            extrasaction="ignore",
        )
        w.writeheader()
        for lead in leads:
            if not lead.get("email"):
                continue
            w.writerow({
                "email": lead.get("email"),
                "first_name": lead.get("username"),
                "companyName": lead.get("site_title") or lead.get("context") or "",
                "personalization": (lead.get("ask_quote") or "")[:300],
                "website": lead.get("website") or lead.get("ask_url") or "",
                "phone": lead.get("phone") or "",
            })
    files["instantly_csv"] = instantly
    return files
