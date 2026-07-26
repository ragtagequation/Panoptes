"""Free multi-platform deepen: public profiles only, no paid APIs."""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from app.discovery.contacts import enrich_lead_contacts, harvest_from_text
from app.discovery.extract import extract_from_text, extract_from_url
from app.discovery.httputil import fetch_text
from app.scrapers.stealth import random_delay
from app.web.helpers import PLATFORM_SCRAPERS, env_get, get_scraper

logger = logging.getLogger(__name__)

# Prefer contact-rich free scrapers first
DEEPEN_PRIORITY = (
    "instagram",
    "linkedin",
    "linktree",
    "github",
    "youtube",
    "tiktok",
    "pinterest",
    "twitch",
    "facebook",
    "x",
)

MAX_HANDLES_PER_LEAD = 3


def deepen_lead(
    lead: dict[str, Any],
    *,
    scrape_sites: bool = True,
    platforms: Optional[list[str]] = None,
) -> dict[str, Any]:
    """
    Scrape linked public social profiles and merge email/phone/website/bio.
    Free only: existing scrapers + light public HTML for Facebook/X when reachable.
    """
    out = dict(lead)
    handles = _collect_handles(out)
    if platforms:
        allowed = {p.lower() for p in platforms}
        handles = [(p, h) for p, h in handles if p in allowed]
    handles = _prioritize(handles)[:MAX_HANDLES_PER_LEAD]
    if not handles:
        out["deepened_platforms"] = []
        return out

    deepened: list[str] = []
    notes: list[str] = []
    has_linkedin_cookie = bool(env_get("LINKEDIN_COOKIE"))

    for platform, username in handles:
        if platform == "linkedin" and not has_linkedin_cookie:
            notes.append("linkedin:skipped_no_cookie")
            continue
        try:
            profile = _scrape_public(platform, username)
        except Exception as e:
            logger.debug("deepen %s/%s failed: %s", platform, username, e)
            notes.append(f"{platform}:error")
            continue
        if not profile:
            notes.append(f"{platform}:empty")
            continue
        out = _merge_profile(out, profile, platform)
        deepened.append(platform)
        notes.append(f"{platform}:ok")
        # Respect polite delays from registry when available
        delay = PLATFORM_SCRAPERS.get(platform, (None, None, (0.8, 1.8)))[2]
        random_delay(delay[0], delay[1])

    if scrape_sites and out.get("website") and not out.get("email"):
        try:
            out = enrich_lead_contacts(out, scrape_site=True)
        except Exception as e:
            logger.debug("post-deepen site enrich failed: %s", e)

    out["deepened_platforms"] = deepened
    out["deepen_notes"] = notes
    out["contactable"] = bool(out.get("email") or out.get("phone"))
    out["complete_contact"] = bool(out.get("email") and out.get("phone"))
    return out


def _collect_handles(lead: dict[str, Any]) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add(platform: str, username: str) -> None:
        platform = (platform or "").lower().strip()
        username = (username or "").strip().lstrip("@").strip("/")
        if not platform or not username:
            return
        if platform == "twitter":
            platform = "x"
        key = (platform, username.lower())
        if key in seen:
            return
        seen.add(key)
        found.append((platform, username))

    for item in lead.get("linked_handles") or []:
        if isinstance(item, dict):
            add(item.get("platform") or "", item.get("username") or "")
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            add(str(item[0]), str(item[1]))

    plat = (lead.get("platform") or "").lower()
    user = lead.get("username") or ""
    if plat in DEEPEN_PRIORITY or plat in PLATFORM_SCRAPERS:
        add(plat, user)

    blob = " ".join(
        str(lead.get(k) or "")
        for k in ("ask_quote", "evidence", "bio", "website", "profile_url", "ask_url", "context")
    )
    for platform, handle in extract_from_text(blob):
        add(platform, handle)
    for url_field in ("website", "profile_url", "ask_url"):
        hit = extract_from_url(str(lead.get(url_field) or ""))
        if hit:
            add(hit[0], hit[1])

    return found


def _prioritize(handles: list[tuple[str, str]]) -> list[tuple[str, str]]:
    rank = {p: i for i, p in enumerate(DEEPEN_PRIORITY)}
    return sorted(handles, key=lambda ph: rank.get(ph[0], 99))


def _scrape_public(platform: str, username: str) -> Optional[dict[str, Any]]:
    if platform in PLATFORM_SCRAPERS:
        scraper, _delays = get_scraper(platform)
        return scraper(username)
    if platform == "facebook":
        return _scrape_facebook_public(username)
    if platform == "x":
        return _scrape_x_public(username)
    return None


def _scrape_facebook_public(username: str) -> Optional[dict[str, Any]]:
    """Best-effort public Page HTML only. No login, no CAPTCHA bypass."""
    username = username.strip("/")
    urls = [
        f"https://www.facebook.com/{username}/about",
        f"https://www.facebook.com/{username}",
        f"https://mbasic.facebook.com/{username}",
    ]
    for url in urls:
        html = fetch_text(url)
        if not html or len(html) < 200:
            continue
        if "login" in html.lower()[:2000] and "about" not in html.lower()[:1500]:
            # Often redirected to login wall — skip
            continue
        harvested = harvest_from_text(html)
        title = _first_match(html, r"<title[^>]*>([^<]+)</title>") or username
        return {
            "username": username,
            "full_name": title.replace(" | Facebook", "").strip()[:120],
            "bio": _clip_text(_strip_tags(html), 400),
            "email": harvested["emails"][0] if harvested["emails"] else None,
            "phone": harvested["phones"][0] if harvested["phones"] else None,
            "website": harvested["websites"][0] if harvested["websites"] else None,
            "platform": "facebook",
            "profile_url": f"https://www.facebook.com/{username}",
        }
    return None


def _scrape_x_public(username: str) -> Optional[dict[str, Any]]:
    """Best-effort public profile HTML only. No login, no CAPTCHA bypass."""
    username = username.lstrip("@")
    urls = [
        f"https://x.com/{username}",
        f"https://twitter.com/{username}",
        f"https://nitter.net/{username}",
    ]
    for url in urls:
        html = fetch_text(url)
        if not html or len(html) < 200:
            continue
        harvested = harvest_from_text(html)
        # Prefer bio-ish meta description
        bio = _first_match(html, r'<meta\s+name="description"\s+content="([^"]+)"') or ""
        if not bio:
            bio = _first_match(html, r'<meta\s+property="og:description"\s+content="([^"]+)"') or ""
        title = _first_match(html, r"<title[^>]*>([^<]+)</title>") or username
        if not (bio or harvested["emails"] or harvested["phones"] or harvested["websites"]):
            continue
        return {
            "username": username,
            "full_name": title.split("(@")[0].strip()[:120],
            "bio": bio[:400],
            "email": harvested["emails"][0] if harvested["emails"] else None,
            "phone": harvested["phones"][0] if harvested["phones"] else None,
            "website": harvested["websites"][0] if harvested["websites"] else None,
            "platform": "x",
            "profile_url": f"https://x.com/{username}",
        }
    return None


def _merge_profile(lead: dict[str, Any], profile: dict[str, Any], platform: str) -> dict[str, Any]:
    out = dict(lead)
    if profile.get("full_name") and not out.get("full_name"):
        out["full_name"] = profile["full_name"]
    if profile.get("bio"):
        existing = out.get("bio") or ""
        out["bio"] = (existing + "\n" + profile["bio"]).strip()[:1200]
        # Also harvest contacts from bio text
        harvested = harvest_from_text(profile["bio"])
        if harvested["emails"] and not out.get("email"):
            out["email"] = harvested["emails"][0]
            out["email_source"] = f"{platform}_bio"
        if harvested["phones"] and not out.get("phone"):
            out["phone"] = harvested["phones"][0]
            out["phone_source"] = f"{platform}_bio"
        if harvested["websites"] and not out.get("website"):
            out["website"] = harvested["websites"][0]

    if profile.get("email") and not out.get("email"):
        out["email"] = profile["email"]
        out["email_source"] = platform
    if profile.get("phone") and not out.get("phone"):
        out["phone"] = profile["phone"]
        out["phone_source"] = platform
    if profile.get("website") and not out.get("website"):
        out["website"] = profile["website"]
    if profile.get("profile_url") and not out.get("deepened_profile_url"):
        out["deepened_profile_url"] = profile["profile_url"]
    if profile.get("headline") and not out.get("what_they_do"):
        out["what_they_do"] = profile["headline"]
    elif profile.get("bio") and not out.get("what_they_do"):
        out["what_they_do"] = _clip_text(profile["bio"], 160)

    handles = list(out.get("linked_handles") or [])
    key = (platform, (profile.get("username") or "").lower())
    if key[1] and not any(
        (h.get("platform") if isinstance(h, dict) else None) == platform
        and (h.get("username") if isinstance(h, dict) else "").lower() == key[1]
        for h in handles
    ):
        handles.append({"platform": platform, "username": profile.get("username")})
        out["linked_handles"] = handles
    return out


def _first_match(text: str, pattern: str) -> str:
    m = re.search(pattern, text, re.I)
    return (m.group(1).strip() if m else "")


def _strip_tags(html: str) -> str:
    text = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", html)
    text = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _clip_text(text: str, n: int) -> str:
    text = re.sub(r"\s+", " ", (text or "").strip())
    return text if len(text) <= n else text[: n - 1].rstrip() + "..."
