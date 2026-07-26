"""Extract public emails/phones and summarize websites (no paid APIs)."""

from __future__ import annotations

import logging
import re
from html import unescape
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

import httpx

from app.scrapers.stealth import get_httpx_proxy, random_delay, random_user_agent

logger = logging.getLogger(__name__)

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
EMAIL_BLACKLIST = {
    "example.com", "test.com", "email.com", "youremail.com", "domain.com",
    "sentry.io", "wixpress.com", "googleapis.com", "w3.org", "schema.org",
    "gravatar.com", "wordpress.com", "github.com", "noreply", "no-reply",
    "donotreply", "privacy@", "abuse@", "support@github",
}
SOCIAL_HOSTS = {
    "reddit.com", "www.reddit.com", "old.reddit.com", "instagram.com",
    "www.instagram.com", "tiktok.com", "www.tiktok.com", "linkedin.com",
    "www.linkedin.com", "github.com", "www.github.com", "youtube.com",
    "www.youtube.com", "youtu.be", "twitter.com", "x.com", "facebook.com",
    "www.facebook.com", "linktr.ee", "duckduckgo.com", "google.com",
    "www.google.com", "medium.com", "substack.com",
}
WEBSITE_RE = re.compile(
    r"https?://[^\s<>\"']+|www\.[^\s<>\"']+",
    re.I,
)
PHONE_PATTERNS = [
    re.compile(r"\+1[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}"),
    re.compile(r"\+?\d{1,3}[-.\s]\(?\d{3}\)[-.\s]?\d{3}[-.\s]?\d{4}"),
    re.compile(r"\(\d{3}\)[-.\s]?\d{3}[-.\s]?\d{4}"),
    re.compile(r"(?:tel:|wa\.me/|whatsapp\.com/send\?phone=)([+\d][\d\s\-().]{8,20})", re.I),
    # Common US/local formats without country code
    re.compile(r"(?<!\d)(\d{3}[-.\s]\d{3}[-.\s]\d{4})(?!\d)"),
    re.compile(r"(?:Phone|Tel|Call|Mobile|Office)\s*[:\-]\s*([+\d\(\)\-.\s]{10,20})", re.I),
]


def extract_emails(text: str) -> list[str]:
    if not text:
        return []
    found = []
    seen = set()
    for email in EMAIL_RE.findall(text):
        lower = email.lower()
        if any(b in lower for b in EMAIL_BLACKLIST):
            continue
        if any(lower.endswith(ext) for ext in (".png", ".jpg", ".gif", ".css", ".js", ".svg")):
            continue
        if lower in seen:
            continue
        seen.add(lower)
        found.append(email)
    return found


def extract_phones(text: str) -> list[str]:
    if not text:
        return []
    found = []
    seen = set()
    for pattern in PHONE_PATTERNS:
        for m in pattern.finditer(text):
            raw = m.group(1) if m.lastindex else m.group(0)
            raw = raw.replace("tel:", "").strip()
            clean = re.sub(r"[^\d+]", "", raw)
            if not (10 <= len(clean.lstrip("+")) <= 15):
                continue
            if clean in seen:
                continue
            seen.add(clean)
            found.append(raw if raw.startswith("+") else raw)
    return found


def extract_websites(text: str) -> list[str]:
    if not text:
        return []
    urls = []
    seen = set()
    for m in WEBSITE_RE.finditer(text):
        url = m.group(0).rstrip(".,);]")
        if not url.startswith("http"):
            url = "https://" + url
        try:
            host = urlparse(url).netloc.lower()
        except ValueError:
            continue
        if not host:
            continue
        if host.startswith("www."):
            host = host[4:]
        if host in SOCIAL_HOSTS or host.endswith(".reddit.com"):
            continue
        if host in seen:
            continue
        seen.add(host)
        urls.append(url)
    return urls


def harvest_from_text(text: str) -> dict[str, Any]:
    return {
        "emails": extract_emails(text),
        "phones": extract_phones(text),
        "websites": extract_websites(text),
    }


def summarize_website(url: str, timeout: float = 12) -> dict[str, Any]:
    """Fetch a public website and return title, what they do, contacts.

    Prefer Firecrawl when FIRECRAWL_API_KEY is set; otherwise raw HTML scrape.
    """
    result = {
        "website": url,
        "site_title": "",
        "what_they_do": "",
        "email": None,
        "phone": None,
        "emails_found": [],
        "phones_found": [],
        "scrape_source": "http",
    }
    if not url:
        return result
    if not url.startswith("http"):
        url = "https://" + url

    # Firecrawl first when available
    try:
        from app.providers.firecrawl import firecrawl_available, scrape_url
        if firecrawl_available():
            fc = scrape_url(url, timeout=max(timeout, 40))
            if fc:
                blob = " ".join([fc.get("text") or "", fc.get("html") or "", fc.get("markdown") or ""])
                emails = extract_emails(blob)
                phones = extract_phones(blob)
                result["site_title"] = fc.get("title") or ""
                result["what_they_do"] = fc.get("description") or _clip_plain(fc.get("text") or "", 320)
                result["emails_found"] = emails
                result["phones_found"] = phones
                result["email"] = emails[0] if emails else None
                result["phone"] = phones[0] if phones else None
                result["scrape_source"] = "firecrawl"
                result["website"] = url
                if result["email"] or result["phone"] or result["what_they_do"]:
                    return result
    except Exception as e:
        logger.debug("Firecrawl path skipped: %s", e)

    pages = [
        url,
        url.rstrip("/") + "/contact",
        url.rstrip("/") + "/contact-us",
        url.rstrip("/") + "/contactus",
        url.rstrip("/") + "/about",
        url.rstrip("/") + "/about-us",
        url.rstrip("/") + "/get-in-touch",
        url.rstrip("/") + "/support",
    ]
    proxy = get_httpx_proxy()
    html_chunks: list[str] = []

    for page in pages:
        try:
            with httpx.Client(timeout=timeout, follow_redirects=True, proxy=proxy) as client:
                resp = client.get(page, headers={"User-Agent": random_user_agent()})
            if resp.status_code >= 400:
                continue
            html = resp.text or ""
            html_chunks.append(html)
            if not result["site_title"]:
                result["site_title"] = _page_title(html)
            if not result["what_they_do"]:
                result["what_they_do"] = _what_they_do(html)
            emails = extract_emails(html)
            phones = extract_phones(html)
            result["emails_found"].extend(emails)
            result["phones_found"].extend(phones)
            if emails and not result["email"]:
                result["email"] = emails[0]
            if phones and not result["phone"]:
                result["phone"] = phones[0]
            if result["email"] and result["phone"] and result["what_they_do"]:
                break
            random_delay(0.25, 0.6)
        except Exception as e:
            logger.debug("Website scrape failed for %s: %s", page, e)

    result["emails_found"] = list(dict.fromkeys(result["emails_found"]))
    result["phones_found"] = list(dict.fromkeys(result["phones_found"]))
    if not result["website"]:
        result["website"] = url
    return result


def _clip_plain(text: str, n: int) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    return text if len(text) <= n else text[: n - 1].rstrip() + "..."


def enrich_lead_contacts(lead: dict[str, Any], *, scrape_site: bool = True) -> dict[str, Any]:
    """Fill email/phone/website/what_they_do from public text + optional site scrape."""
    out = dict(lead)
    blob = " ".join([
        str(out.get("evidence") or ""),
        str(out.get("context") or ""),
        str(out.get("bio") or ""),
        str(out.get("profile_url") or ""),
        str(out.get("website") or ""),
    ])
    harvested = harvest_from_text(blob)

    if harvested["emails"] and not out.get("email"):
        out["email"] = harvested["emails"][0]
        out["email_source"] = out.get("email_source") or "public_text"
    if harvested["phones"] and not out.get("phone"):
        out["phone"] = harvested["phones"][0]
        out["phone_source"] = out.get("phone_source") or "public_text"
    if harvested["websites"] and not out.get("website"):
        out["website"] = harvested["websites"][0]

    website = out.get("website") or ""
    # Prefer non-social profile URLs as websites when they look like personal sites
    if not website:
        profile = out.get("profile_url") or ""
        host = urlparse(profile).netloc.lower().removeprefix("www.")
        if profile.startswith("http") and host and host not in SOCIAL_HOSTS:
            website = profile
            out["website"] = website

    if scrape_site and website:
        site = summarize_website(website)
        if site.get("site_title"):
            out["site_title"] = site["site_title"]
        if site.get("what_they_do"):
            out["what_they_do"] = site["what_they_do"]
        if site.get("email") and not out.get("email"):
            out["email"] = site["email"]
            out["email_source"] = "website"
        if site.get("phone") and not out.get("phone"):
            out["phone"] = site["phone"]
            out["phone_source"] = "website"
        if site.get("emails_found"):
            out["emails_found"] = ",".join(site["emails_found"][:8])
        if not out.get("website"):
            out["website"] = site.get("website") or website

    # Optional paid enrichers when still missing contacts
    out = _apply_paid_enrichers(out)

    # Boost score when contact info is present
    score = int(out.get("interest_score") or 0)
    if out.get("email"):
        score += 12
    if out.get("phone"):
        score += 10
    if out.get("website"):
        score += 6
    if out.get("what_they_do"):
        score += 4
    out["interest_score"] = min(score, 100)
    return out


def _apply_paid_enrichers(lead: dict[str, Any]) -> dict[str, Any]:
    out = dict(lead)
    website = out.get("website") or ""
    name = out.get("full_name") or out.get("username") or ""
    domain = ""
    if website:
        try:
            domain = urlparse(website if "://" in website else "https://" + website).netloc.lower().removeprefix("www.")
        except Exception:
            domain = ""

    if not out.get("email") and domain:
        try:
            from app.providers.hunter import find_email, hunter_available
            if hunter_available() and name:
                email = find_email(str(name), domain)
                if email:
                    out["email"] = email
                    out["email_source"] = "hunter"
        except Exception as e:
            logger.debug("Hunter enrich skipped: %s", e)

    if (not out.get("email") or not out.get("phone")) and (domain or name):
        try:
            from app.providers.apollo import apollo_available, find_person
            if apollo_available():
                hit = find_person(
                    full_name=str(name),
                    domain=domain,
                    linkedin_url=out.get("profile_url") if "linkedin.com" in str(out.get("profile_url") or "") else "",
                )
                if hit:
                    if hit.get("email") and not out.get("email"):
                        out["email"] = hit["email"]
                        out["email_source"] = "apollo"
                    if hit.get("phone") and not out.get("phone"):
                        out["phone"] = hit["phone"]
                        out["phone_source"] = "apollo"
                    if hit.get("title") and not out.get("what_they_do"):
                        out["what_they_do"] = hit["title"]
                    if hit.get("full_name") and not out.get("full_name"):
                        out["full_name"] = hit["full_name"]
                    if hit.get("website") and not out.get("website"):
                        out["website"] = hit["website"]
        except Exception as e:
            logger.debug("Apollo enrich skipped: %s", e)

    if not out.get("email") and domain:
        try:
            from app.providers.hunter import domain_search, hunter_available
            if hunter_available():
                rows = domain_search(domain, limit=3)
                if rows and rows[0].get("email"):
                    out["email"] = rows[0]["email"]
                    out["email_source"] = "hunter_domain"
                    if rows[0].get("full_name") and not out.get("full_name"):
                        out["full_name"] = rows[0]["full_name"]
        except Exception as e:
            logger.debug("Hunter domain search skipped: %s", e)

    return out


def enrich_leads_batch(
    leads: list[dict[str, Any]],
    *,
    scrape_sites: bool = True,
    max_site_scrapes: int = 40,
    on_progress=None,
) -> list[dict[str, Any]]:
    enriched = []
    sites_done = 0
    for i, lead in enumerate(leads, 1):
        do_site = scrape_sites and sites_done < max_site_scrapes
        if on_progress and i % 5 == 0:
            on_progress(f"Enriching contacts {i}/{len(leads)}…")
        item = enrich_lead_contacts(lead, scrape_site=do_site)
        if do_site and item.get("website"):
            sites_done += 1
        enriched.append(item)
    return enriched


def _page_title(html: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    if not m:
        return ""
    title = unescape(re.sub(r"\s+", " ", m.group(1))).strip()
    return title[:160]


def _what_they_do(html: str) -> str:
    # meta description
    for pattern in (
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']description["\']',
        r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']',
    ):
        m = re.search(pattern, html, re.I)
        if m:
            desc = unescape(re.sub(r"\s+", " ", m.group(1))).strip()
            if len(desc) > 40:
                return desc[:320]

    # first meaningful paragraph
    for m in re.finditer(r"<p[^>]*>(.*?)</p>", html, re.I | re.S):
        text = unescape(re.sub(r"<[^>]+>", " ", m.group(1)))
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) > 60 and "cookie" not in text.lower():
            return text[:320]
    return ""
