"""LLM draft rewriting — OpenAI or Anthropic when keys are present."""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

import httpx

from app.web.helpers import env_get

logger = logging.getLogger(__name__)


def llm_available() -> bool:
    return bool(env_get("OPENAI_API_KEY") or env_get("ANTHROPIC_API_KEY"))


def polish_drafts(
    lead: dict[str, Any],
    offer_info: dict[str, Any],
    base_drafts: dict[str, str],
) -> dict[str, str]:
    """
    Improve template drafts with GPT or Claude. Falls back to base_drafts on any failure.
    Evidence-locked: must keep the ask quote.
    """
    if not llm_available():
        return base_drafts
    quote = (lead.get("ask_quote") or lead.get("evidence") or "").strip()
    if not quote or not any(base_drafts.values()):
        return base_drafts

    prompt = (
        "You help salespeople reply to public unanswered asks.\n"
        "Rewrite these outreach drafts to be warmer and more specific.\n"
        "Rules:\n"
        "1) Keep the exact ask quote (or a faithful short version) in every draft.\n"
        "2) Be helpful first, soft CTA second. No spammy hype.\n"
        "3) Return strict JSON with keys: public_reply, dm_or_email, call_opener, sms.\n"
        "4) sms under 280 chars. call_opener under 45 seconds spoken.\n\n"
        f"Offer: {offer_info.get('offer') or ''}\n"
        f"Niche: {offer_info.get('niche') or ''}\n"
        f"Asker: {lead.get('username') or lead.get('full_name') or ''}\n"
        f"Ask quote: {quote[:500]}\n"
        f"Ask URL: {lead.get('ask_url') or ''}\n"
        f"What they do: {lead.get('what_they_do') or lead.get('site_title') or ''}\n\n"
        f"Current drafts JSON:\n{json.dumps(base_drafts)}\n"
    )

    raw = _chat(prompt)
    if not raw:
        return base_drafts
    parsed = _parse_json(raw)
    if not parsed:
        return base_drafts
    out = dict(base_drafts)
    for key in ("public_reply", "dm_or_email", "call_opener", "sms"):
        val = (parsed.get(key) or "").strip()
        if val:
            out[key] = val
    return out


def _chat(prompt: str) -> Optional[str]:
    if env_get("OPENAI_API_KEY"):
        return _openai(prompt)
    if env_get("ANTHROPIC_API_KEY"):
        return _anthropic(prompt)
    return None


def _openai(prompt: str) -> Optional[str]:
    key = env_get("OPENAI_API_KEY")
    model = env_get("OPENAI_MODEL", default="gpt-4o-mini")
    try:
        with httpx.Client(timeout=45) as client:
            resp = client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "temperature": 0.4,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": "You write concise evidence-locked outreach. Reply with JSON only."},
                        {"role": "user", "content": prompt},
                    ],
                },
            )
        if resp.status_code >= 400:
            logger.debug("OpenAI HTTP %s: %s", resp.status_code, resp.text[:200])
            return None
        return (((resp.json() or {}).get("choices") or [{}])[0].get("message") or {}).get("content")
    except Exception as e:
        logger.debug("OpenAI failed: %s", e)
        return None


def _anthropic(prompt: str) -> Optional[str]:
    key = env_get("ANTHROPIC_API_KEY")
    model = env_get("ANTHROPIC_MODEL", default="claude-3-5-haiku-latest")
    try:
        with httpx.Client(timeout=45) as client:
            resp = client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "max_tokens": 1200,
                    "temperature": 0.4,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
        if resp.status_code >= 400:
            logger.debug("Anthropic HTTP %s: %s", resp.status_code, resp.text[:200])
            return None
        blocks = (resp.json() or {}).get("content") or []
        texts = [b.get("text") for b in blocks if isinstance(b, dict) and b.get("type") == "text"]
        return "\n".join(t for t in texts if t)
    except Exception as e:
        logger.debug("Anthropic failed: %s", e)
        return None


def _parse_json(raw: str) -> Optional[dict[str, Any]]:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(raw[start : end + 1])
            except Exception:
                return None
    return None
