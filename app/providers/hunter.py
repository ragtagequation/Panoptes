"""Hunter.io email finder — used when HUNTER_API_KEY is set."""

from __future__ import annotations

import logging
from typing import Optional
from urllib.parse import urlparse

import httpx

from app.web.helpers import env_get

logger = logging.getLogger(__name__)


def hunter_available() -> bool:
    return bool(env_get("HUNTER_API_KEY"))


def find_email(full_name: str, website_or_domain: str) -> Optional[str]:
    key = env_get("HUNTER_API_KEY")
    if not key or not full_name or not website_or_domain:
        return None
    domain = _domain(website_or_domain)
    if not domain:
        return None
    parts = [p for p in full_name.strip().split() if p]
    if not parts:
        return None
    first, last = parts[0], parts[-1] if len(parts) > 1 else ""
    try:
        with httpx.Client(timeout=20) as client:
            resp = client.get(
                "https://api.hunter.io/v2/email-finder",
                params={
                    "domain": domain,
                    "first_name": first,
                    "last_name": last,
                    "api_key": key,
                },
            )
        if resp.status_code >= 400:
            return None
        data = (resp.json() or {}).get("data") or {}
        email = data.get("email")
        return email if email and "@" in email else None
    except Exception as e:
        logger.debug("Hunter error: %s", e)
        return None


def domain_search(domain: str, *, limit: int = 5) -> list[dict]:
    key = env_get("HUNTER_API_KEY")
    domain = _domain(domain)
    if not key or not domain:
        return []
    try:
        with httpx.Client(timeout=20) as client:
            resp = client.get(
                "https://api.hunter.io/v2/domain-search",
                params={"domain": domain, "limit": limit, "api_key": key},
            )
        if resp.status_code >= 400:
            return []
        emails = ((resp.json() or {}).get("data") or {}).get("emails") or []
        out = []
        for row in emails[:limit]:
            if row.get("value"):
                out.append({
                    "email": row["value"],
                    "full_name": f"{row.get('first_name') or ''} {row.get('last_name') or ''}".strip(),
                    "position": row.get("position") or "",
                    "source": "hunter",
                })
        return out
    except Exception as e:
        logger.debug("Hunter domain search failed: %s", e)
        return []


def _domain(website_or_domain: str) -> str:
    raw = (website_or_domain or "").strip()
    if not raw:
        return ""
    if "://" in raw or "/" in raw or raw.startswith("www."):
        host = urlparse(raw if "://" in raw else "https://" + raw).netloc.lower()
    else:
        host = raw.lower()
    return host.removeprefix("www.")
