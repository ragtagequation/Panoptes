"""Extract public profile handles from URLs and text."""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import unquote, urlparse

PROFILE_PATTERNS = [
    ("instagram", re.compile(r"(?:https?://)?(?:www\.)?instagram\.com/([A-Za-z0-9._]{2,40})/?", re.I)),
    ("tiktok", re.compile(r"(?:https?://)?(?:www\.)?tiktok\.com/@([A-Za-z0-9._]{2,40})", re.I)),
    ("linkedin", re.compile(r"(?:https?://)?(?:[\w.]+)?linkedin\.com/in/([A-Za-z0-9%-_.]{2,100})", re.I)),
    ("github", re.compile(r"(?:https?://)?(?:www\.)?github\.com/([A-Za-z0-9-]{1,39})(?:/|$)", re.I)),
    ("youtube", re.compile(r"(?:https?://)?(?:www\.)?youtube\.com/@([A-Za-z0-9._-]{2,50})", re.I)),
    ("twitch", re.compile(r"(?:https?://)?(?:www\.)?twitch\.tv/([A-Za-z0-9_]{2,40})", re.I)),
    ("pinterest", re.compile(r"(?:https?://)?(?:www\.)?pinterest\.com/([A-Za-z0-9_]{2,40})/?", re.I)),
    ("linktree", re.compile(r"(?:https?://)?(?:www\.)?linktr\.ee/([A-Za-z0-9._-]{2,40})", re.I)),
    ("facebook", re.compile(
        r"(?:https?://)?(?:www\.|m\.|mbasic\.)?facebook\.com/(?:profile\.php\?id=)?([A-Za-z0-9.]{3,80})/?",
        re.I,
    )),
    ("x", re.compile(r"(?:https?://)?(?:www\.)?(?:twitter|x)\.com/@?([A-Za-z0-9_]{1,40})/?", re.I)),
]

SKIP_FACEBOOK = {
    "people", "pages", "groups", "watch", "marketplace", "gaming", "events",
    "login", "recover", "help", "privacy", "policies", "settings", "share",
    "photo", "photos", "video", "videos", "reel", "reels", "story", "stories",
    "permalink.php", "story.php",
}

SKIP_X = {
    "home", "explore", "search", "settings", "i", "intent", "share", "login",
    "signup", "tos", "privacy", "messages", "notifications", "compose",
}

SKIP_GITHUB = {
    "topics", "explore", "settings", "marketplace", "pulls", "issues",
    "notifications", "about", "pricing", "enterprise", "features", "orgs",
    "search", "login", "signup", "new", "organizations", "sponsors",
}

SKIP_INSTAGRAM = {"p", "reel", "reels", "stories", "explore", "accounts", "direct", "legal"}


def extract_from_url(url: str) -> Optional[tuple[str, str]]:
    if not url:
        return None
    url = unquote(url.strip())
    for platform, pattern in PROFILE_PATTERNS:
        m = pattern.search(url)
        if not m:
            continue
        handle = m.group(1).rstrip("/")
        if platform == "github" and handle.lower() in SKIP_GITHUB:
            continue
        if platform == "instagram" and handle.lower() in SKIP_INSTAGRAM:
            continue
        if platform == "facebook" and handle.lower() in SKIP_FACEBOOK:
            continue
        if platform == "x" and handle.lower() in SKIP_X:
            continue
        if platform == "linkedin":
            handle = handle.split("?")[0]
        return platform, handle
    return None


def extract_from_text(text: str) -> list[tuple[str, str]]:
    if not text:
        return []
    found: list[tuple[str, str]] = []
    seen = set()
    for platform, pattern in PROFILE_PATTERNS:
        for m in pattern.finditer(text):
            handle = unquote(m.group(1)).rstrip("/")
            if platform == "github" and handle.lower() in SKIP_GITHUB:
                continue
            if platform == "instagram" and handle.lower() in SKIP_INSTAGRAM:
                continue
            if platform == "facebook" and handle.lower() in SKIP_FACEBOOK:
                continue
            if platform == "x" and handle.lower() in SKIP_X:
                continue
            key = (platform, handle.lower())
            if key in seen:
                continue
            seen.add(key)
            found.append((platform, handle))
    return found


def normalize_topic_queries(
    topic: str,
    company: str = "",
    extras: Optional[list[str]] = None,
    *,
    contact_focused: bool = False,
    business_focused: bool = False,
) -> list[str]:
    topic = (topic or "").strip()
    company = (company or "").strip()
    queries = []
    if topic:
        queries.append(topic)
        if business_focused:
            queries.extend([
                f'{topic} business contact email phone',
                f'{topic} company "contact us" OR "call us" OR "email us"',
                f'{topic} agency OR services OR consultant phone',
                f'{topic} "mailto:" OR "@gmail.com" OR "@yahoo.com" OR office phone',
                f'{topic} near me business address phone',
            ])
        else:
            queries.append(f"{topic} recommendations OR looking for")
            queries.append(f"{topic} agency OR consultant OR coach")
        if contact_focused and not business_focused:
            queries.append(f"{topic} email OR contact OR founder")
    if company and company.lower() not in topic.lower():
        queries.append(f"{company} {topic}".strip())
        if business_focused:
            queries.append(f"{company} contact email phone")
    if extras:
        queries.extend([q.strip() for q in extras if q and q.strip()])

    out, seen = [], set()
    for q in queries:
        key = q.lower()
        if key not in seen:
            seen.add(key)
            out.append(q)
    return out[:8]


def domain_hint(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
        return host[4:] if host.startswith("www.") else host
    except Exception:
        return ""
