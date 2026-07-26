"""Discover interested people from public Reddit archives / search."""

from __future__ import annotations

import logging
from typing import Any

from app.discovery.extract import extract_from_text
from app.discovery.httputil import fetch_json
from app.scrapers.stealth import random_delay

logger = logging.getLogger(__name__)

SKIP_AUTHORS = {"[deleted]", "AutoModerator", "automoderator", "None", "null"}

# Cache whether reddit.com JSON is blocked in this environment
_reddit_blocked: bool | None = None


def search_reddit(query: str, limit: int = 40) -> list[dict[str, Any]]:
    """Return lead dicts from Reddit posts + comments matching query."""
    leads: list[dict[str, Any]] = []
    seen_authors: set[str] = set()

    for post in _reddit_posts(query, limit=limit):
        author = (post.get("author") or "").strip()
        title = post.get("title") or ""
        selftext = post.get("selftext") or post.get("body") or ""
        subreddit = str(post.get("subreddit") or "").replace("r/", "")
        permalink = post.get("permalink") or ""
        if permalink and not str(permalink).startswith("http"):
            url = f"https://www.reddit.com{permalink}"
        else:
            url = permalink or (post.get("url") or "")
        snippet = f"{title} {selftext}".strip()[:280]

        if author and author not in SKIP_AUTHORS and author.lower() not in seen_authors:
            seen_authors.add(author.lower())
            leads.append({
                "username": author,
                "platform": "reddit",
                "profile_url": f"https://www.reddit.com/user/{author}",
                "source": post.get("_source", "reddit_search"),
                "evidence": snippet,
                "query": query,
                "context": f"r/{subreddit}" if subreddit else "reddit",
                "interest_score": _score(query, snippet, subreddit),
            })

        for platform, handle in extract_from_text(f"{title}\n{selftext}\n{post.get('url') or ''}"):
            leads.append({
                "username": handle,
                "platform": platform,
                "profile_url": _profile_url(platform, handle),
                "source": "reddit_link",
                "evidence": snippet,
                "query": query,
                "context": f"r/{subreddit}" if subreddit else "reddit",
                "interest_score": _score(query, snippet, subreddit) + 5,
            })

    for c in _reddit_comments(query, limit=limit):
        author = (c.get("author") or "").strip()
        body = (c.get("body") or "").strip()
        subreddit = str(c.get("subreddit") or "").replace("r/", "")
        if not author or author in SKIP_AUTHORS or author.lower() in seen_authors or not body:
            continue
        seen_authors.add(author.lower())
        leads.append({
            "username": author,
            "platform": "reddit",
            "profile_url": f"https://www.reddit.com/user/{author}",
            "source": c.get("_source", "reddit_comment"),
            "evidence": body[:280],
            "query": query,
            "context": f"r/{subreddit}" if subreddit else "reddit",
            "interest_score": _score(query, body, subreddit) + 8,
        })

    return leads


def _official_reddit_ok() -> bool:
    global _reddit_blocked
    if _reddit_blocked is True:
        return False
    if _reddit_blocked is False:
        return True
    data = fetch_json(
        "https://www.reddit.com/search.json",
        params={"q": "test", "limit": 1, "type": "link", "raw_json": 1},
    )
    ok = bool(data and isinstance(data, dict) and "data" in data)
    _reddit_blocked = not ok
    if not ok:
        logger.info("reddit.com JSON blocked here — using PullPush archive")
    return ok


def _reddit_posts(query: str, limit: int) -> list[dict]:
    posts: list[dict] = []

    if _official_reddit_ok():
        data = fetch_json(
            "https://www.reddit.com/search.json",
            params={
                "q": query,
                "sort": "relevance",
                "limit": min(limit, 100),
                "type": "link",
                "raw_json": 1,
            },
        )
        for child in (((data or {}).get("data") or {}).get("children")) or []:
            item = child.get("data") or {}
            item["_source"] = "reddit_search"
            posts.append(item)
        if posts:
            random_delay(0.4, 0.9)
            return posts[:limit]

    data = fetch_json(
        "https://api.pullpush.io/reddit/search/submission/",
        params={"q": query, "size": min(limit, 100), "sort": "desc", "sort_type": "score"},
    )
    if isinstance(data, dict):
        for item in data.get("data") or []:
            if isinstance(item, dict):
                item["_source"] = "pullpush_submission"
                posts.append(item)
    random_delay(0.35, 0.8)
    return posts[:limit]


def _reddit_comments(query: str, limit: int) -> list[dict]:
    comments: list[dict] = []

    if _official_reddit_ok():
        data = fetch_json(
            "https://www.reddit.com/search.json",
            params={
                "q": query,
                "sort": "relevance",
                "limit": min(limit, 100),
                "type": "comment",
                "raw_json": 1,
            },
        )
        for child in (((data or {}).get("data") or {}).get("children")) or []:
            item = child.get("data") or {}
            item["_source"] = "reddit_comment"
            comments.append(item)
        if comments:
            return comments[:limit]

    data = fetch_json(
        "https://api.pullpush.io/reddit/search/comment/",
        params={"q": query, "size": min(limit, 100), "sort": "desc", "sort_type": "score"},
    )
    if isinstance(data, dict):
        for item in data.get("data") or []:
            if isinstance(item, dict):
                item["_source"] = "pullpush_comment"
                comments.append(item)
    return comments[:limit]


def _score(query: str, text: str, subreddit: str) -> int:
    score = 40
    q = query.lower()
    t = (text or "").lower()
    s = (subreddit or "").lower()
    tokens = [tok for tok in q.replace('"', " ").split() if len(tok) > 2]
    hits = sum(1 for tok in tokens if tok in t)
    score += min(hits * 8, 32)
    if any(w in t for w in ("looking for", "need", "recommend", "help with", "anyone know", "hiring", "buy")):
        score += 15
    if any(tok in s for tok in tokens):
        score += 10
    return min(score, 100)


def _profile_url(platform: str, handle: str) -> str:
    mapping = {
        "instagram": f"https://instagram.com/{handle}",
        "tiktok": f"https://tiktok.com/@{handle}",
        "linkedin": f"https://linkedin.com/in/{handle}",
        "github": f"https://github.com/{handle}",
        "youtube": f"https://youtube.com/@{handle}",
        "twitch": f"https://twitch.tv/{handle}",
        "pinterest": f"https://pinterest.com/{handle}",
        "linktree": f"https://linktr.ee/{handle}",
    }
    return mapping.get(platform, "")
