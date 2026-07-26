"""Firecrawl site scrape — used when FIRECRAWL_API_KEY is set."""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

import httpx

from app.web.helpers import env_get

logger = logging.getLogger(__name__)


def firecrawl_available() -> bool:
    return bool(env_get("FIRECRAWL_API_KEY"))


def scrape_url(url: str, *, timeout: float = 45) -> Optional[dict[str, Any]]:
    """
    Scrape a URL via Firecrawl. Returns markdown/html/metadata or None.
    """
    key = env_get("FIRECRAWL_API_KEY")
    if not key or not url:
        return None
    if not url.startswith("http"):
        url = "https://" + url
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(
                "https://api.firecrawl.dev/v1/scrape",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                json={
                    "url": url,
                    "formats": ["markdown", "html"],
                    "onlyMainContent": False,
                },
            )
        if resp.status_code >= 400:
            logger.warning("Firecrawl HTTP %s for %s", resp.status_code, url)
            return None
        data = resp.json() or {}
        payload = data.get("data") or data
        markdown = payload.get("markdown") or ""
        html = payload.get("html") or ""
        meta = payload.get("metadata") or {}
        title = meta.get("title") or meta.get("ogTitle") or ""
        desc = meta.get("description") or meta.get("ogDescription") or ""
        return {
            "url": url,
            "title": title,
            "description": desc,
            "markdown": markdown,
            "html": html,
            "text": markdown or _strip_html(html),
            "source": "firecrawl",
        }
    except Exception as e:
        logger.debug("Firecrawl failed for %s: %s", url, e)
        return None


def _strip_html(html: str) -> str:
    text = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", html or "")
    text = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()
