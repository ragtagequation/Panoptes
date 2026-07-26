"""LLM complete_text / complete_json with OpenAI, Anthropic, or None."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

import httpx

from app.web.helpers import env_get

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 60.0


def ai_available() -> bool:
    return bool(env_get("OPENAI_API_KEY") or env_get("ANTHROPIC_API_KEY"))


def ai_mode() -> str:
    """Which engine is driving generation right now."""
    if env_get("OPENAI_API_KEY"):
        return "openai"
    if env_get("ANTHROPIC_API_KEY"):
        return "anthropic"
    return "heuristic"


def complete_text(
    prompt: str,
    *,
    system: str = "You are a precise, practical expert. Be concrete.",
    max_tokens: int = 1400,
    temperature: float = 0.4,
) -> Optional[str]:
    """Free-form completion. None when unavailable or on failure."""
    mode = ai_mode()
    if mode == "openai":
        return _openai(prompt, system, max_tokens, temperature, as_json=False)
    if mode == "anthropic":
        return _anthropic(prompt, system, max_tokens, temperature)
    return None


def complete_json(
    prompt: str,
    *,
    system: str = "You are a precise analyst. Reply with valid JSON only.",
    max_tokens: int = 1800,
    temperature: float = 0.3,
) -> Optional[dict[str, Any]]:
    """JSON completion, parsed. None when unavailable or unparseable."""
    mode = ai_mode()
    if mode == "openai":
        raw = _openai(prompt, system, max_tokens, temperature, as_json=True)
    elif mode == "anthropic":
        raw = _anthropic(prompt, system, max_tokens, temperature)
    else:
        return None
    return parse_json(raw) if raw else None


def parse_json(raw: str) -> Optional[dict[str, Any]]:
    """Tolerant JSON extraction — models sometimes wrap output in prose/fences."""
    raw = (raw or "").strip()
    if not raw:
        return None
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.M).strip()
    try:
        out = json.loads(raw)
        return out if isinstance(out, dict) else {"result": out}
    except Exception:
        pass
    start, end = raw.find("{"), raw.rfind("}")
    if start >= 0 and end > start:
        try:
            out = json.loads(raw[start : end + 1])
            return out if isinstance(out, dict) else {"result": out}
        except Exception:
            return None
    return None


def _openai(
    prompt: str,
    system: str,
    max_tokens: int,
    temperature: float,
    *,
    as_json: bool,
) -> Optional[str]:
    key = env_get("OPENAI_API_KEY")
    model = env_get("OPENAI_MODEL", default="gpt-4o-mini")
    body: dict[str, Any] = {
        "model": model,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
    }
    if as_json:
        body["response_format"] = {"type": "json_object"}
    try:
        with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
            resp = client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json=body,
            )
        if resp.status_code >= 400:
            logger.warning("OpenAI HTTP %s: %s", resp.status_code, resp.text[:200])
            return None
        choices = (resp.json() or {}).get("choices") or [{}]
        return (choices[0].get("message") or {}).get("content")
    except Exception as e:
        logger.debug("OpenAI call failed: %s", e)
        return None


def _anthropic(prompt: str, system: str, max_tokens: int, temperature: float) -> Optional[str]:
    key = env_get("ANTHROPIC_API_KEY")
    model = env_get("ANTHROPIC_MODEL", default="claude-3-5-haiku-latest")
    try:
        with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
            resp = client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "system": system,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
        if resp.status_code >= 400:
            logger.warning("Anthropic HTTP %s: %s", resp.status_code, resp.text[:200])
            return None
        blocks = (resp.json() or {}).get("content") or []
        texts = [b.get("text") for b in blocks if isinstance(b, dict) and b.get("type") == "text"]
        return "\n".join(t for t in texts if t) or None
    except Exception as e:
        logger.debug("Anthropic call failed: %s", e)
        return None
