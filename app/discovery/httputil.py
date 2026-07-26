"""Shared HTTP helpers for public discovery sources."""

from __future__ import annotations

import logging
from typing import Any, Optional, Union

import requests

from app.scrapers.stealth import get_requests_proxies, random_user_agent

logger = logging.getLogger(__name__)

TimeoutType = Union[float, tuple[float, float]]

_session: requests.Session | None = None


def _get_session() -> requests.Session:
    global _session
    if _session is None:
        _session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(pool_connections=10, pool_maxsize=10, max_retries=0)
        _session.mount("https://", adapter)
        _session.mount("http://", adapter)
    return _session


def fetch(
    url: str,
    *,
    params: Optional[dict] = None,
    timeout: TimeoutType = (6, 12),
    accept: str = "*/*",
    use_proxy: bool = True,
) -> Optional[requests.Response]:
    ua = random_user_agent()
    headers = {
        "User-Agent": ua,
        "Accept": accept,
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
        "DNT": "1",
    }
    if "reddit.com" in url:
        headers["Accept"] = "application/json,text/html;q=0.9,*/*;q=0.8"
        headers["Referer"] = "https://www.reddit.com/"
    if "duckduckgo.com" in url:
        headers["Referer"] = "https://duckduckgo.com/"
    if "bing.com" in url:
        headers["Referer"] = "https://www.bing.com/"
    if "brave.com" in url:
        headers["Referer"] = "https://search.brave.com/"
    if "yahoo.com" in url:
        headers["Referer"] = "https://search.yahoo.com/"
    if "google.com" in url:
        headers["Referer"] = "https://www.google.com/"

    proxies = get_requests_proxies() if use_proxy else None
    try:
        resp = _get_session().get(
            url,
            params=params,
            headers=headers,
            proxies=proxies,
            timeout=timeout,
        )
        if resp.status_code >= 400:
            logger.warning("HTTP %s for %s", resp.status_code, url)
            return None
        return resp
    except requests.exceptions.Timeout:
        logger.warning("Timeout for %s", url)
        return None
    except Exception as e:
        logger.warning("Request failed for %s: %s", url, e)
        return None


def fetch_json(
    url: str,
    *,
    params: Optional[dict] = None,
    timeout: TimeoutType = (6, 12),
) -> Any:
    resp = fetch(url, params=params, timeout=timeout, accept="application/json")
    if not resp:
        return None
    try:
        return resp.json()
    except Exception:
        return None


def fetch_text(
    url: str,
    *,
    timeout: TimeoutType = (6, 12),
) -> Optional[str]:
    resp = fetch(url, timeout=timeout, accept="text/html,application/xhtml+xml;q=0.9,*/*;q=0.8")
    if not resp:
        return None
    try:
        return resp.text
    except Exception:
        return None
