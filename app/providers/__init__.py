"""Optional third-party API providers — only used when keys are set."""

from __future__ import annotations

from typing import Any

from app.web.helpers import env_get


def provider_status() -> dict[str, bool]:
    return {
        "hunter": bool(env_get("HUNTER_API_KEY")),
        "apollo": bool(env_get("APOLLO_API_KEY")),
        "firecrawl": bool(env_get("FIRECRAWL_API_KEY")),
        "openai": bool(env_get("OPENAI_API_KEY")),
        "anthropic": bool(env_get("ANTHROPIC_API_KEY")),
        "google_places": bool(env_get("GOOGLE_PLACES_API_KEY")),
        "linkedin": bool(env_get("LINKEDIN_COOKIE")),
    }


def active_providers() -> list[str]:
    return [k for k, v in provider_status().items() if v]


def key_preview(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if len(value) <= 8:
        return value[:2] + "…"
    return value[:4] + "…" + value[-2:]
