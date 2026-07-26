"""Google Places Text Search — used when GOOGLE_PLACES_API_KEY is set."""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from app.web.helpers import env_get

logger = logging.getLogger(__name__)


def places_available() -> bool:
    return bool(env_get("GOOGLE_PLACES_API_KEY"))


def search_places(query: str, *, limit: int = 20) -> list[dict[str, Any]]:
    """
    Find businesses via Places Text Search (legacy JSON).
    Returns Panoptes-shaped lead dicts.
    """
    key = env_get("GOOGLE_PLACES_API_KEY")
    query = (query or "").strip()
    if not key or not query:
        return []

    leads: list[dict[str, Any]] = []
    try:
        with httpx.Client(timeout=20) as client:
            resp = client.get(
                "https://maps.googleapis.com/maps/api/place/textsearch/json",
                params={"query": query, "key": key},
            )
        if resp.status_code >= 400:
            logger.warning("Places HTTP %s", resp.status_code)
            return []
        data = resp.json() or {}
        status = data.get("status")
        if status not in ("OK", "ZERO_RESULTS"):
            logger.warning("Places status %s: %s", status, data.get("error_message"))
            return []

        for item in (data.get("results") or [])[: max(1, limit)]:
            place_id = item.get("place_id") or ""
            name = item.get("name") or ""
            address = item.get("formatted_address") or ""
            website = ""
            phone = ""
            email = None
            what = ""
            detail = _place_details(place_id, key) if place_id else {}
            if detail:
                website = detail.get("website") or ""
                phone = detail.get("formatted_phone_number") or detail.get("international_phone_number") or ""
                what = detail.get("editorial_summary", {}).get("overview") or ""
                if not what:
                    types = detail.get("types") or item.get("types") or []
                    what = ", ".join(t.replace("_", " ") for t in types[:4])

            slug = re_slug(name) or place_id[:12] or "place"
            leads.append({
                "username": slug,
                "platform": "website",
                "profile_url": website or f"https://www.google.com/maps/place/?q=place_id:{place_id}",
                "website": website or None,
                "email": email,
                "phone": phone or None,
                "full_name": name,
                "site_title": name,
                "what_they_do": what or address,
                "evidence": f"{name} — {address}".strip(" —"),
                "context": "google_places",
                "source": "google_places",
                "interest_score": 70,
                "found_at": time.time(),
            })
    except Exception as e:
        logger.warning("Places search failed: %s", e)
    return leads


def _place_details(place_id: str, key: str) -> dict[str, Any]:
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.get(
                "https://maps.googleapis.com/maps/api/place/details/json",
                params={
                    "place_id": place_id,
                    "fields": "name,formatted_phone_number,international_phone_number,website,editorial_summary,types",
                    "key": key,
                },
            )
        if resp.status_code >= 400:
            return {}
        data = resp.json() or {}
        if data.get("status") != "OK":
            return {}
        return data.get("result") or {}
    except Exception as e:
        logger.debug("Place details failed: %s", e)
        return {}


def re_slug(name: str) -> str:
    import re
    s = re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")
    return s[:40]
