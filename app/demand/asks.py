"""Hunt public unanswered asks (Reddit + web demand surfaces)."""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

from app.demand.silence import is_demand_text, silence_score
from app.discovery.contacts import harvest_from_text
from app.discovery.extract import extract_from_text, extract_from_url
from app.discovery.httputil import fetch_json
from app.discovery.reddit import _reddit_posts  # reuse internal fetcher
from app.discovery.websearch import search_web, web_search_available
from app.scrapers.stealth import random_delay

logger = logging.getLogger(__name__)

SKIP_AUTHORS = {"[deleted]", "AutoModerator", "automoderator", "None", "null"}
ProgressCb = Callable[[str], None] | None


def hunt_asks(
    queries: list[str],
    *,
    max_comments: int = 2,
    min_silence: int = 55,
    limit_per_query: int = 40,
    include_web: bool = True,
    on_progress: ProgressCb = None,
) -> list[dict[str, Any]]:
    asks: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    def progress(msg: str) -> None:
        if on_progress:
            on_progress(msg)
        logger.info(msg)

    for i, query in enumerate(queries, 1):
        progress(f"Demand hunt {i}/{len(queries)}: {query}")

        # Reddit submissions (best silence signal)
        try:
            posts = _reddit_posts(query, limit=limit_per_query)
        except Exception as e:
            logger.warning("Reddit ask hunt failed: %s", e)
            posts = []

        for post in posts:
            try:
                ask = _ask_from_reddit_post(post, query)
            except Exception as e:
                logger.debug("Skip bad reddit post: %s", e)
                continue
            if not ask:
                continue
            if ask["num_comments"] > max_comments:
                continue
            if ask["silence_score"] < min_silence:
                continue
            if ask["ask_url"] in seen_urls:
                continue
            if not is_demand_text(ask["ask_quote"]):
                # still keep high-silence commercial-looking titles
                if ask["silence_score"] < 80:
                    continue
            seen_urls.add(ask["ask_url"])
            asks.append(ask)

        # Web demand-ish pages (looking for / RFP language)
        if include_web and web_search_available():
            try:
                hits = search_web(query, limit_per_site=8, contact_hunt=True, business_hunt=True)
                for hit in hits:
                    ask = _ask_from_web_hit(hit, query)
                    if not ask or ask["ask_url"] in seen_urls:
                        continue
                    seen_urls.add(ask["ask_url"])
                    asks.append(ask)
            except Exception as e:
                logger.warning("Web demand hunt failed: %s", e)

        # Google Places businesses (when key present) — treat as contactable demand surface
        if include_web:
            try:
                from app.providers.places import places_available, search_places
                if places_available() and i <= 3:
                    progress(f"  Google Places: {query}")
                    for hit in search_places(query, limit=8):
                        ask = _ask_from_web_hit(hit, query)
                        if not ask or ask["ask_url"] in seen_urls:
                            continue
                        seen_urls.add(ask["ask_url"])
                        asks.append(ask)
            except Exception as e:
                logger.warning("Places demand hunt failed: %s", e)

        random_delay(0.3, 0.7)

    asks.sort(key=lambda a: (-a.get("silence_score", 0), a.get("age_days") or 999))
    progress(f"Collected {len(asks)} unanswered / public demand hits")
    return asks


def _ask_from_reddit_post(post: dict[str, Any], query: str) -> dict[str, Any] | None:
    author = (post.get("author") or "").strip()
    if not author or author in SKIP_AUTHORS:
        return None
    title = post.get("title") or ""
    body = post.get("selftext") or post.get("body") or ""
    quote = f"{title}\n{body}".strip()
    if len(quote) < 20:
        return None

    permalink = post.get("permalink") or ""
    if permalink and not str(permalink).startswith("http"):
        url = f"https://www.reddit.com{permalink}"
    else:
        url = permalink or (post.get("url") or "")
    if not url:
        return None

    subreddit = str(post.get("subreddit") or "").replace("r/", "")
    num_comments = int(post.get("num_comments") or 0)
    created = post.get("created_utc")
    sil = silence_score(
        num_comments=num_comments,
        created_utc=float(created) if created else None,
        title=title,
        body=body,
    )

    harvested = harvest_from_text(f"{title}\n{body}\n{post.get('url') or ''}")
    socials = extract_from_text(f"{title}\n{body}\n{post.get('url') or ''}")

    return {
        "ask_id": f"reddit:{post.get('id') or url}",
        "ask_quote": quote[:600],
        "ask_url": url,
        "ask_source": "reddit",
        "username": author,
        "platform": "reddit",
        "profile_url": f"https://www.reddit.com/user/{author}",
        "context": f"r/{subreddit}" if subreddit else "reddit",
        "query": query,
        "evidence": quote[:280],
        "num_comments": num_comments,
        "created_utc": created,
        "email": harvested["emails"][0] if harvested["emails"] else None,
        "phone": harvested["phones"][0] if harvested["phones"] else None,
        "website": harvested["websites"][0] if harvested["websites"] else None,
        "linked_handles": [{"platform": p, "username": h} for p, h in socials[:5]],
        **sil,
        "interest_score": sil["silence_score"],
        "status": "new",
        "outcome": None,
        "found_at": time.time(),
    }


def _ask_from_web_hit(hit: dict[str, Any], query: str) -> dict[str, Any] | None:
    evidence = (hit.get("evidence") or hit.get("site_title") or "").strip()
    url = hit.get("website") or hit.get("profile_url") or ""
    if not url or not evidence:
        return None
    # Treat business/contact pages as medium silence opportunities
    sil = silence_score(num_comments=0, created_utc=time.time() - 3 * 86400, title=evidence, body="")
    sil["silence_label"] = "web_demand"
    sil["is_unanswered"] = True
    sil["silence_score"] = min(88, max(60, sil["silence_score"] - 5))

    blob = " ".join([
        evidence,
        url,
        str(hit.get("profile_url") or ""),
        str(hit.get("website") or ""),
        str(hit.get("context") or ""),
    ])
    socials = extract_from_text(blob)
    top = extract_from_url(url)
    if top and top not in socials:
        socials = [top] + socials
    # If the hit itself is a social profile, keep it as a linked handle
    hit_plat = (hit.get("platform") or "").lower()
    hit_user = hit.get("username") or ""
    if hit_plat and hit_user:
        socials = [(hit_plat, hit_user)] + socials

    linked = []
    seen = set()
    for p, h in socials[:5]:
        key = (p, h.lower())
        if key in seen:
            continue
        seen.add(key)
        linked.append({"platform": p, "username": h})

    return {
        "ask_id": f"web:{url}",
        "ask_quote": evidence[:600],
        "ask_url": url,
        "ask_source": hit.get("source") or "web",
        "username": hit.get("username") or "",
        "platform": hit.get("platform") or "website",
        "profile_url": hit.get("profile_url") or url,
        "context": hit.get("context") or "web",
        "query": query,
        "evidence": evidence[:280],
        "num_comments": 0,
        "created_utc": None,
        "email": hit.get("email"),
        "phone": hit.get("phone"),
        "website": hit.get("website") or (url if hit.get("platform") == "website" else None),
        "linked_handles": linked,
        "what_they_do": hit.get("what_they_do"),
        "site_title": hit.get("site_title"),
        **sil,
        "interest_score": sil["silence_score"],
        "status": "new",
        "outcome": None,
        "found_at": time.time(),
    }


# Re-export for typing clarity if reddit internals change
def fetch_user_about(username: str) -> dict[str, Any] | None:
    data = fetch_json(f"https://www.reddit.com/user/{username}/about.json")
    if not data:
        data = fetch_json(f"https://api.pullpush.io/reddit/user/{username}/about")  # may 404
    return data
