"""Apollo people match — used when APOLLO_API_KEY is set."""

from __future__ import annotations

import logging
from typing import Any, Optional
from urllib.parse import urlparse

import httpx

from app.web.helpers import env_get

logger = logging.getLogger(__name__)


def apollo_available() -> bool:
    return bool(env_get("APOLLO_API_KEY"))


def find_person(
    *,
    full_name: str = "",
    domain: str = "",
    email: str = "",
    linkedin_url: str = "",
) -> Optional[dict[str, Any]]:
    """
    Match a person via Apollo. Returns email/phone/title/org when found.
    """
    key = env_get("APOLLO_API_KEY")
    if not key:
        return None
    domain = _clean_domain(domain)
    first, last = _split_name(full_name)
    body: dict[str, Any] = {"reveal_personal_emails": True}
    if email:
        body["email"] = email
    if first:
        body["first_name"] = first
    if last:
        body["last_name"] = last
    if domain:
        body["organization_domain"] = domain
        body["domain"] = domain
    if linkedin_url:
        body["linkedin_url"] = linkedin_url
    if not any(body.get(k) for k in ("email", "first_name", "organization_domain", "linkedin_url", "domain")):
        return None

    try:
        with httpx.Client(timeout=25) as client:
            resp = client.post(
                "https://api.apollo.io/api/v1/people/match",
                headers={
                    "Content-Type": "application/json",
                    "Cache-Control": "no-cache",
                    "X-Api-Key": key,
                },
                json=body,
            )
        if resp.status_code >= 400:
            logger.debug("Apollo HTTP %s: %s", resp.status_code, resp.text[:200])
            return None
        person = (resp.json() or {}).get("person") or {}
        if not person:
            return None
        emails = []
        if person.get("email"):
            emails.append(person["email"])
        for e in person.get("personal_emails") or []:
            if e and e not in emails:
                emails.append(e)
        phones = []
        for p in person.get("phone_numbers") or []:
            raw = p.get("sanitized_number") or p.get("raw_number") if isinstance(p, dict) else str(p)
            if raw:
                phones.append(raw)
        org = person.get("organization") or {}
        return {
            "email": emails[0] if emails else None,
            "phone": phones[0] if phones else None,
            "full_name": person.get("name") or full_name,
            "title": person.get("title") or "",
            "website": org.get("website_url") or (f"https://{domain}" if domain else None),
            "company": org.get("name") or "",
            "linkedin_url": person.get("linkedin_url") or linkedin_url or "",
            "source": "apollo",
        }
    except Exception as e:
        logger.debug("Apollo match failed: %s", e)
        return None


def enrich_from_domain(domain: str, *, full_name: str = "") -> Optional[dict[str, Any]]:
    return find_person(full_name=full_name, domain=domain)


def _clean_domain(domain_or_url: str) -> str:
    raw = (domain_or_url or "").strip()
    if not raw:
        return ""
    if "://" in raw or raw.startswith("www."):
        host = urlparse(raw if "://" in raw else "https://" + raw).netloc.lower()
    else:
        host = raw.lower()
    return host.removeprefix("www.").split("/")[0]


def _split_name(full_name: str) -> tuple[str, str]:
    parts = [p for p in (full_name or "").strip().split() if p]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[-1]
