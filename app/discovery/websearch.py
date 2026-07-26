"""Discover businesses and contacts via Google + Yahoo web search."""

from __future__ import annotations

import logging
import re
import time
from html import unescape
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from app.discovery.contacts import extract_emails, extract_phones, harvest_from_text
from app.discovery.extract import extract_from_text, extract_from_url
from app.discovery.httputil import fetch
from app.scrapers.stealth import random_delay

logger = logging.getLogger(__name__)

_SEARCH_TIMEOUT = (2.5, 8.0)

_yahoo_fails = 0
_google_fails = 0
_google_disabled = False
_web_disabled_until = 0.0
_COOLDOWN_SECONDS = 120

SOCIAL_HOST_BITS = (
    "instagram.com", "tiktok.com", "linkedin.com", "github.com",
    "youtube.com", "reddit.com", "twitter.com", "x.com", "facebook.com",
    "yahoo.com", "google.com", "bing.com", "duckduckgo.com",
    "uservoice.com", "wikipedia.org", "apple.com", "play.google.com",
    "microsoft.com", "amazon.com", "yelp.com",
)


def reset_web_search_state() -> None:
    global _yahoo_fails, _google_fails, _google_disabled, _web_disabled_until
    _yahoo_fails = 0
    _google_fails = 0
    _google_disabled = False
    _web_disabled_until = 0.0


def web_search_available() -> bool:
    return time.time() >= _web_disabled_until


def _disable_web(reason: str) -> None:
    global _web_disabled_until
    _web_disabled_until = time.time() + _COOLDOWN_SECONDS
    logger.warning(
        "Web search paused for %ss (%s). Discovery continues with other sources.",
        _COOLDOWN_SECONDS,
        reason,
    )


def search_web(
    query: str,
    limit_per_site: int = 8,
    contact_hunt: bool = True,
    business_hunt: bool = False,
) -> list[dict[str, Any]]:
    leads: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    if not web_search_available():
        logger.info("Web search cooldown active — skipping")
        return []

    searches = [query]
    if business_hunt:
        searches.extend([
            f'{query} business phone email contact',
            f'{query} "contact us" OR "call now" OR "get a quote"',
            f'{query} company website office phone',
        ])
    elif contact_hunt:
        searches.append(f'{query} (email OR contact OR site:linkedin.com/in)')
    else:
        searches.append(f"{query} site:linkedin.com/in")

    # Cap request volume
    searches = searches[:4]

    for q in searches:
        if not web_search_available():
            break

        results = _multi_search(q)
        if results is None:
            break

        for title, url, snippet in results[: max(limit_per_site, 10)]:
            blob = f"{title}\n{snippet}\n{url}"
            candidates = []
            extracted = extract_from_url(url)
            if extracted:
                candidates.append(extracted)
            candidates.extend(extract_from_text(blob))

            for platform, handle in candidates:
                key = (platform, handle.lower())
                if key in seen:
                    continue
                seen.add(key)
                lead = {
                    "username": handle,
                    "platform": platform,
                    "profile_url": url if platform in url else "",
                    "source": "web_search",
                    "evidence": (snippet or title or "")[:280],
                    "query": q,
                    "context": "business web search" if business_hunt else "web search",
                    "interest_score": _score(query, f"{title} {snippet}"),
                }
                _attach_contacts(lead, blob, url)
                leads.append(lead)

            # Always try to keep business website leads (even if a social handle also matched)
            biz = _website_or_email_lead(query, q, title, url, snippet, business=business_hunt)
            if biz:
                key = (biz["platform"], biz["username"].lower())
                if key not in seen:
                    seen.add(key)
                    leads.append(biz)

        random_delay(0.35, 0.7)

    return leads


def _multi_search(query: str) -> list[tuple[str, str, str]] | None:
    """Try Google first, then Yahoo. None = web search should stop."""
    global _google_disabled

    if not _google_disabled:
        g = _google_search(query)
        if g:
            return g

    return _yahoo_search(query)


def _google_search(query: str) -> list[tuple[str, str, str]]:
    """Best-effort Google HTML scrape. Disabled after repeated blocks."""
    global _google_fails, _google_disabled

    resp = fetch(
        "https://www.google.com/search",
        params={"q": query, "hl": "en", "num": "15", "pws": "0"},
        accept="text/html",
        timeout=_SEARCH_TIMEOUT,
        use_proxy=False,
    )
    if resp is None:
        _google_fails += 1
        if _google_fails >= 2:
            _google_disabled = True
            logger.warning("Google search blocked/unreachable — using Yahoo for web results")
        return []

    text = resp.text or ""
    lower = text.lower()
    if "captcha" in lower or "/sorry/" in lower or "unusual traffic" in lower:
        _google_fails += 1
        if _google_fails >= 1:
            _google_disabled = True
            logger.warning("Google returned captcha — using Yahoo for web results")
        return []

    results = _parse_google(text)
    if results:
        _google_fails = 0
        logger.info("Web search via google: %s hits", len(results))
    else:
        # Empty parse often means blocked markup
        _google_fails += 1
        if _google_fails >= 2:
            _google_disabled = True
            logger.warning("Google returned no parseable results — using Yahoo")
    return results


def _parse_google(html: str) -> list[tuple[str, str, str]]:
    results: list[tuple[str, str, str]] = []
    seen: set[str] = set()

    # Classic result blocks
    for block in re.split(r'class="[^"]*g\b', html)[1:]:
        title_m = re.search(
            r'<a[^>]+href="(https?://[^"]+|\/url\?[^"]+)"[^>]*>.*?<h3[^>]*>(.*?)</h3>',
            block,
            re.I | re.S,
        )
        if not title_m:
            title_m = re.search(r'<a[^>]+href="(https?://[^"]+|\/url\?[^"]+)"[^>]*>(.*?)</a>', block, re.I | re.S)
        if not title_m:
            continue
        url = _unwrap_google(unescape(title_m.group(1)))
        title = re.sub(r"<[^>]+>", "", unescape(title_m.group(2))).strip()
        snip_m = re.search(r'data-sncf="1"[^>]*>(.*?)</div>|<div[^>]*class="[^"]*VwiC3b[^"]*"[^>]*>(.*?)</div>', block, re.I | re.S)
        snippet = ""
        if snip_m:
            snippet = re.sub(r"<[^>]+>", "", unescape(snip_m.group(1) or snip_m.group(2) or "")).strip()
        if not url.startswith("http") or any(b in url for b in SOCIAL_HOST_BITS[:0]):
            pass
        if not url.startswith("http") or "google." in urlparse(url).netloc:
            continue
        if url in seen:
            continue
        seen.add(url)
        results.append((title, url, snippet))

    # Fallback: /url?q= wrappers
    if len(results) < 3:
        for m in re.finditer(r'/url\?q=(https?[^&"]+)', html):
            url = unquote(m.group(1))
            if "google." in urlparse(url).netloc or url in seen:
                continue
            seen.add(url)
            results.append(("", url, ""))
            if len(results) >= 15:
                break

    return results


def _unwrap_google(href: str) -> str:
    href = unescape(href)
    if href.startswith("/url?"):
        qs = parse_qs(urlparse("https://www.google.com" + href).query)
        if "q" in qs:
            return unquote(qs["q"][0])
        if "url" in qs:
            return unquote(qs["url"][0])
    if "google." in href and ("/url?" in href or "url=" in href):
        qs = parse_qs(urlparse(href).query)
        if "q" in qs:
            return unquote(qs["q"][0])
        if "url" in qs:
            return unquote(qs["url"][0])
    return href


def _yahoo_search(query: str) -> list[tuple[str, str, str]] | None:
    global _yahoo_fails

    for attempt in range(2):
        resp = fetch(
            "https://search.yahoo.com/search",
            params={"p": query, "n": "20"},
            accept="text/html",
            timeout=_SEARCH_TIMEOUT,
            use_proxy=False,
        )
        if resp is not None:
            results = _parse_yahoo(resp.text)
            _yahoo_fails = 0
            logger.info("Web search via yahoo: %s hits", len(results))
            return results
        if attempt == 0:
            random_delay(0.4, 0.8)

    _yahoo_fails += 1
    if _yahoo_fails >= 2:
        _disable_web("Yahoo/Google search unreachable")
        return None
    return []


def _parse_yahoo(html: str) -> list[tuple[str, str, str]]:
    results: list[tuple[str, str, str]] = []
    seen_urls: set[str] = set()

    for block in re.split(r'class="[^"]*algo[^"]*"', html)[1:]:
        title_m = re.search(r"<h3[^>]*>\s*<a[^>]+href=\"([^\"]+)\"[^>]*>(.*?)</a>", block, re.I | re.S)
        if not title_m:
            title_m = re.search(r"<a[^>]+href=\"([^\"]+)\"[^>]*>(.*?)</a>", block, re.I | re.S)
        if not title_m:
            continue
        url = _unwrap_yahoo(unescape(title_m.group(1)))
        title = re.sub(r"<[^>]+>", "", unescape(title_m.group(2))).strip()
        snip_m = re.search(
            r'(?:class="[^"]*compText[^"]*"|class="[^"]*fc-falcon[^"]*")[^>]*>(.*?)</(?:p|span|div)',
            block,
            re.I | re.S,
        )
        snippet = ""
        if snip_m:
            snippet = re.sub(r"<[^>]+>", "", unescape(snip_m.group(1))).strip()
        if url.startswith("http") and "yahoo.com" not in url and url not in seen_urls:
            seen_urls.add(url)
            results.append((title, url, snippet))

    if len(results) < 3:
        for m in re.finditer(r"/RU=([^/]+)/", html):
            url = unquote(m.group(1))
            if not url.startswith("http") or "yahoo.com" in url or url in seen_urls:
                continue
            seen_urls.add(url)
            results.append(("", url, ""))
            if len(results) >= 15:
                break

    return results


def _unwrap_yahoo(href: str) -> str:
    href = unescape(href)
    m = re.search(r"/RU=([^/]+)/", href)
    if m:
        return unquote(m.group(1))
    if "yahoo.com" in href and "RU=" in href:
        try:
            qs = parse_qs(urlparse(href).query)
            if "RU" in qs:
                return unquote(qs["RU"][0])
        except Exception:
            pass
    return href


def _attach_contacts(lead: dict[str, Any], blob: str, url: str) -> None:
    harvested = harvest_from_text(blob)
    if harvested["emails"]:
        lead["email"] = harvested["emails"][0]
        lead["email_source"] = "search_snippet"
    if harvested["phones"]:
        lead["phone"] = harvested["phones"][0]
        lead["phone_source"] = "search_snippet"
    if harvested["websites"]:
        lead["website"] = harvested["websites"][0]
    elif url and not any(x in url for x in ("yahoo.com", "google.com", "bing.com")):
        host = urlparse(url).netloc.lower().removeprefix("www.")
        if host and not any(host.endswith(s) for s in SOCIAL_HOST_BITS):
            lead.setdefault("website", url)


def _website_or_email_lead(
    topic: str,
    query: str,
    title: str,
    url: str,
    snippet: str,
    *,
    business: bool = False,
) -> dict[str, Any] | None:
    blob = f"{title}\n{snippet}\n{url}"
    emails = extract_emails(blob)
    phones = extract_phones(blob)
    harvested = harvest_from_text(blob)
    website = harvested["websites"][0] if harvested["websites"] else ""
    host = urlparse(url).netloc.lower().removeprefix("www.") if url else ""
    if host and not any(host.endswith(s) or s in host for s in SOCIAL_HOST_BITS):
        website = website or url

    if not emails and not phones and not website:
        return None

    # Prefer business website identity
    if website:
        username = host or urlparse(website).netloc.lower().removeprefix("www.")
        platform = "website"
        profile_url = website
    elif emails:
        username = emails[0].split("@")[0][:40]
        platform = "email"
        profile_url = f"mailto:{emails[0]}"
    else:
        username = re.sub(r"\D", "", phones[0])[-10:]
        platform = "phone"
        profile_url = ""

    lead = {
        "username": username,
        "platform": platform,
        "profile_url": profile_url,
        "source": "google_business" if business else "web_contact",
        "evidence": (snippet or title or "")[:280],
        "query": query,
        "context": "business search" if business else "contact search",
        "interest_score": _score(topic, f"{title} {snippet}") + (18 if business else 10),
        "site_title": title[:160],
    }
    if emails:
        lead["email"] = emails[0]
        lead["email_source"] = "search_snippet"
    if phones:
        lead["phone"] = phones[0]
        lead["phone_source"] = "search_snippet"
    if website:
        lead["website"] = website
    return lead


def _score(query: str, text: str) -> int:
    score = 35
    q = query.lower()
    t = (text or "").lower()
    tokens = [tok for tok in q.replace('"', " ").split() if len(tok) > 2 and tok not in ("site:", "or")]
    hits = sum(1 for tok in tokens if tok in t)
    score += min(hits * 7, 35)
    if any(w in t for w in (
        "looking for", "need", "recommend", "consultant", "coach", "agency",
        "founder", "contact", "phone", "email", "business", "services",
    )):
        score += 12
    return min(score, 95)
