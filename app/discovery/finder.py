"""Orchestrate public topic lead discovery and export."""

from __future__ import annotations

import csv
import logging
import re
import time
from pathlib import Path
from typing import Any, Callable, Optional

from app.discovery.contacts import enrich_leads_batch, harvest_from_text
from app.discovery.extract import normalize_topic_queries
from app.discovery.github import search_github
from app.discovery.reddit import search_reddit
from app.discovery.websearch import reset_web_search_state, search_web, web_search_available

logger = logging.getLogger(__name__)

ProgressCb = Optional[Callable[[str], None]]

SCRAPEABLE = {
    "instagram", "tiktok", "linkedin", "github", "youtube",
    "twitch", "pinterest", "linktree",
}


def _has_complete_contacts(lead: dict[str, Any]) -> bool:
    email = (lead.get("email") or "").strip()
    phone = (lead.get("phone") or "").strip()
    return bool(email and "@" in email and phone)


def discover_leads(
    topic: str,
    *,
    company: str = "",
    sources: Optional[list[str]] = None,
    max_per_query: int = 35,
    target_leads: int = 50,
    extras: Optional[list[str]] = None,
    enrich_contacts: bool = True,
    scrape_sites: bool = True,
    require_complete_contacts: bool = False,
    on_progress: ProgressCb = None,
) -> list[dict[str, Any]]:
    """
    Find businesses/people for a topic from Reddit + Google/Yahoo web search.

    Contact enrichment and email+phone filtering are optional.
    """
    topic = (topic or "").strip()
    if not topic:
        raise ValueError("topic is required")

    target = max(5, min(int(target_leads or 50), 300))
    # Need many more candidates when requiring email+phone
    fetch_cap = min(500, int(target * (4.5 if require_complete_contacts else 1.6)) + 20)
    per_query = max(15, min(max_per_query, max(20, target)))

    # Prefer web/business discovery; keep reddit/github optional
    wanted = {s.lower() for s in (sources or ["web", "reddit", "github"])}
    if "web" not in wanted and require_complete_contacts:
        wanted.add("web")

    # Always scrape sites when we need complete contacts
    if require_complete_contacts:
        enrich_contacts = True
        scrape_sites = True

    queries = normalize_topic_queries(
        topic,
        company=company,
        extras=extras,
        contact_focused=True,
        business_focused=True,
    )
    reset_web_search_state()

    def progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)
        logger.info(msg)

    raw: list[dict[str, Any]] = []
    web_done = 0
    max_web_queries = min(len(queries), 6 if require_complete_contacts else 2)

    for i, query in enumerate(queries, 1):
        progress(f"Query {i}/{len(queries)}: {query} (need {target} complete contacts)")

        # Web / Google business search first — best source of emails+phones
        if "web" in wanted and web_done < max_web_queries:
            # Google Places when key present (highest-quality business rows)
            try:
                from app.providers.places import places_available, search_places
                if places_available() and web_done == 0:
                    progress(f"  Google Places: {query}")
                    raw.extend(search_places(query, limit=min(20, max(8, target // 2))))
            except Exception as e:
                logger.warning("Places search failed: %s", e)

            if not web_search_available():
                progress("  Web: skipped (provider cooldown)")
            else:
                progress(f"  Google/Web businesses: {query}")
                try:
                    hits = search_web(
                        query,
                        limit_per_site=min(12, max(6, target // 5)),
                        contact_hunt=True,
                        business_hunt=True,
                    )
                    raw.extend(hits)
                    web_done += 1
                except Exception as e:
                    logger.warning("Web search failed: %s", e)
                    web_done += 1

        if "reddit" in wanted:
            progress(f"  Reddit: {query}")
            try:
                reddit_leads = search_reddit(query, limit=per_query)
                for lead in reddit_leads:
                    _seed_contacts_from_evidence(lead)
                raw.extend(reddit_leads)
            except Exception as e:
                logger.warning("Reddit search failed: %s", e)

        if "github" in wanted and i <= 2:
            progress(f"  GitHub: {query}")
            try:
                raw.extend(search_github(query, limit=min(per_query, 20)))
            except Exception as e:
                logger.warning("GitHub search failed: %s", e)

        # Early enrich a slice of website leads so we can stop once we have enough
        website_candidates = [
            l for l in _dedupe_and_rank(raw, topic=topic, company=company)
            if l.get("website") or l.get("platform") == "website"
        ]
        if require_complete_contacts and website_candidates and enrich_contacts:
            # Progressive scrape of newest website batch
            unscored = [l for l in website_candidates if not _has_complete_contacts(l)][: min(25, target * 2)]
            if unscored:
                progress(f"  Scraping {len(unscored)} business sites for email+phone…")
                enriched_slice = enrich_leads_batch(
                    unscored,
                    scrape_sites=True,
                    max_site_scrapes=len(unscored),
                    on_progress=None,
                )
                # Merge enriched back into raw by replacing matching keys
                enriched_map = {
                    ((e.get("platform") or ""), (e.get("username") or "").lower()): e
                    for e in enriched_slice
                }
                for idx, lead in enumerate(raw):
                    key = ((lead.get("platform") or ""), (lead.get("username") or "").lower())
                    if key in enriched_map:
                        raw[idx] = {**lead, **enriched_map[key]}

        complete_so_far = sum(
            1 for l in _dedupe_and_rank(raw, topic=topic, company=company)
            if _has_complete_contacts(l)
        )
        progress(f"  Complete contacts so far: {complete_so_far}/{target}")
        if complete_so_far >= target:
            progress("Reached target complete contacts — wrapping up")
            break
        if len(_dedupe_and_rank(raw, topic=topic, company=company)) >= fetch_cap:
            progress(f"Reached candidate cap ({fetch_cap})")
            break

    leads = _dedupe_and_rank(raw, topic=topic, company=company)
    progress(f"Found {len(leads)} unique candidates")

    if enrich_contacts and leads:
        # Prefer website/business leads for final scrape pass
        leads_sorted = sorted(
            leads,
            key=lambda x: (
                0 if x.get("platform") == "website" else 1,
                0 if x.get("website") else 1,
                0 if x.get("email") else 1,
                0 if x.get("phone") else 1,
                -int(x.get("interest_score") or 0),
            ),
        )
        pool = leads_sorted[: min(len(leads_sorted), fetch_cap)]
        # Skip already-complete to save time; scrape the rest
        already = [l for l in pool if _has_complete_contacts(l)]
        todo = [l for l in pool if not _has_complete_contacts(l)]
        need = max(0, target * 3 - len(already))
        todo = todo[:need]

        if todo:
            progress(f"Final contact scrape on {len(todo)} leads…")
            todo = enrich_leads_batch(
                todo,
                scrape_sites=scrape_sites,
                max_site_scrapes=min(80, len(todo)),
                on_progress=progress,
            )
        leads = already + todo
        leads = sorted(
            leads,
            key=lambda x: (
                0 if _has_complete_contacts(x) else 1,
                -int(x.get("interest_score") or 0),
                x.get("platform", ""),
                x.get("username", ""),
            ),
        )

    if require_complete_contacts:
        leads = [l for l in leads if _has_complete_contacts(l)]
        progress(
            f"Filtered to {len(leads)} leads with BOTH email and phone "
            f"(requested {target})"
        )
    else:
        with_email = sum(1 for l in leads if l.get("email"))
        with_phone = sum(1 for l in leads if l.get("phone"))
        progress(f"Contacts — emails: {with_email}, phones: {with_phone}")

    leads = leads[:target]
    progress(f"Returning {len(leads)} leads")
    return leads


def _seed_contacts_from_evidence(lead: dict[str, Any]) -> None:
    harvested = harvest_from_text(
        f"{lead.get('evidence', '')} {lead.get('profile_url', '')} {lead.get('website', '')}"
    )
    if harvested["emails"] and not lead.get("email"):
        lead["email"] = harvested["emails"][0]
        lead["email_source"] = "public_text"
    if harvested["phones"] and not lead.get("phone"):
        lead["phone"] = harvested["phones"][0]
        lead["phone_source"] = "public_text"
    if harvested["websites"] and not lead.get("website"):
        lead["website"] = harvested["websites"][0]


def _dedupe_and_rank(leads: list[dict[str, Any]], topic: str, company: str) -> list[dict[str, Any]]:
    best: dict[tuple[str, str], dict[str, Any]] = {}
    for lead in leads:
        platform = (lead.get("platform") or "").lower().strip()
        username = (lead.get("username") or "").strip().lstrip("@")
        if not platform or not username:
            continue
        # Prefer website/email identity keys when present
        if lead.get("website"):
            host = re.sub(r"^www\.", "", re.sub(r"^https?://", "", lead["website"]).split("/")[0]).lower()
            key = ("website", host)
        elif lead.get("email"):
            key = ("email", str(lead["email"]).lower())
        else:
            key = (platform, username.lower())

        score = int(lead.get("interest_score") or 0)
        score += _bonus(topic, company, lead)
        merged = {**lead, "username": username, "platform": platform, "interest_score": min(score, 100)}
        prev = best.get(key)
        if not prev or merged["interest_score"] > prev["interest_score"]:
            if prev:
                merged = _merge_lead(prev, merged)
            best[key] = merged
        else:
            best[key] = _merge_lead(merged, prev)

    return sorted(best.values(), key=lambda x: (-x["interest_score"], x["platform"], x["username"]))


def _merge_lead(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    out = dict(a)
    for field in (
        "email", "phone", "website", "what_they_do", "site_title",
        "email_source", "phone_source", "emails_found", "profile_url",
    ):
        if not out.get(field) and b.get(field):
            out[field] = b[field]
    if int(b.get("interest_score") or 0) > int(out.get("interest_score") or 0):
        out["interest_score"] = b["interest_score"]
        if b.get("evidence"):
            out["evidence"] = b["evidence"]
    return out


def _bonus(topic: str, company: str, lead: dict[str, Any]) -> int:
    text = f"{lead.get('evidence', '')} {lead.get('context', '')}".lower()
    bonus = 0
    for tok in re.findall(r"[a-z0-9]{3,}", (topic or "").lower()):
        if tok in text:
            bonus += 2
    if company and company.lower() in text:
        bonus += 6
    if lead.get("source") in ("google_business", "web_contact", "web_search"):
        bonus += 8
    if lead.get("platform") == "website":
        bonus += 10
    if lead.get("email"):
        bonus += 8
    if lead.get("phone"):
        bonus += 8
    return min(bonus, 30)


def save_leads(
    leads: list[dict[str, Any]],
    out_dir: Path,
    *,
    topic: str,
    prefix: str = "leads",
) -> dict[str, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    slug = re.sub(r"[^a-z0-9]+", "_", (topic or "topic").lower()).strip("_")[:40] or "topic"
    files: dict[str, str] = {}

    fields = [
        "username", "platform", "email", "phone", "website", "site_title",
        "what_they_do", "interest_score", "email_source", "phone_source",
        "profile_url", "source", "context", "query", "evidence", "topic",
    ]

    master_name = f"{prefix}_{slug}_{stamp}.csv"
    with open(out_dir / master_name, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for lead in leads:
            writer.writerow({**lead, "topic": topic})
    files["master_csv"] = master_name

    contact_rows = [l for l in leads if _has_complete_contacts(l)]
    if contact_rows:
        contact_name = f"{prefix}_{slug}_contacts_{stamp}.csv"
        with open(out_dir / contact_name, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            for lead in contact_rows:
                writer.writerow({**lead, "topic": topic})
        files["contacts_csv"] = contact_name

    by_platform: dict[str, list[str]] = {}
    for lead in leads:
        platform = lead["platform"]
        if platform not in SCRAPEABLE:
            continue
        by_platform.setdefault(platform, []).append(lead["username"])

    for platform, users in by_platform.items():
        uniq, seen = [], set()
        for u in users:
            k = u.lower()
            if k not in seen:
                seen.add(k)
                uniq.append(u)
        name = f"{prefix}_{slug}_{platform}_{stamp}.txt"
        (out_dir / name).write_text("\n".join(uniq) + ("\n" if uniq else ""), encoding="utf-8")
        files[platform] = name

    return files


def group_for_scrape(leads: list[dict[str, Any]]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for lead in leads:
        platform = lead.get("platform")
        username = lead.get("username")
        if not platform or not username or platform not in SCRAPEABLE:
            continue
        groups.setdefault(platform, [])
        if username not in groups[platform]:
            groups[platform].append(username)
    return groups
