"""Discover public GitHub users related to a topic (no token required)."""

from __future__ import annotations

import logging
from typing import Any

from app.discovery.httputil import fetch_json
from app.scrapers.stealth import random_delay

logger = logging.getLogger(__name__)


def search_github(query: str, limit: int = 30) -> list[dict[str, Any]]:
    leads: list[dict[str, Any]] = []
    seen: set[str] = set()

    # Users whose bio/location/name match topic keywords
    users = fetch_json(
        "https://api.github.com/search/users",
        params={"q": f"{query} in:bio", "per_page": min(limit, 30)},
    )
    if users and isinstance(users, dict):
        for item in users.get("items") or []:
            login = (item.get("login") or "").strip()
            if not login or login.lower() in seen:
                continue
            seen.add(login.lower())
            leads.append({
                "username": login,
                "platform": "github",
                "profile_url": item.get("html_url") or f"https://github.com/{login}",
                "source": "github_user_search",
                "evidence": f"GitHub bio/profile match for '{query}'",
                "query": query,
                "context": "github users",
                "interest_score": 55,
            })

    random_delay(0.7, 1.4)

    # Repositories matching topic — owners are often practitioners
    repos = fetch_json(
        "https://api.github.com/search/repositories",
        params={"q": query, "sort": "updated", "order": "desc", "per_page": min(limit, 30)},
    )
    if repos and isinstance(repos, dict):
        for item in repos.get("items") or []:
            owner = ((item.get("owner") or {}).get("login") or "").strip()
            if not owner or owner.lower() in seen:
                continue
            if ((item.get("owner") or {}).get("type") or "") != "User":
                continue
            seen.add(owner.lower())
            desc = item.get("description") or item.get("full_name") or ""
            leads.append({
                "username": owner,
                "platform": "github",
                "profile_url": f"https://github.com/{owner}",
                "source": "github_repo_owner",
                "evidence": f"Owns repo {item.get('full_name')}: {desc}"[:280],
                "query": query,
                "context": "github repos",
                "interest_score": 50,
            })

    return leads
