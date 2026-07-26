"""Obsidian vault writer — markdown + YAML frontmatter."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.web.helpers import env_get


def vault_path() -> Path | None:
    raw = env_get("OBSIDIAN_VAULT_PATH")
    if not raw:
        return None
    path = Path(raw).expanduser()
    return path if path.exists() and path.is_dir() else path


def export_ask(lead: dict[str, Any], *, offer: str = "", solution: dict[str, Any] | None = None) -> dict[str, Any]:
    root = vault_path()
    if root is None:
        raise ValueError("Set OBSIDIAN_VAULT_PATH to a valid vault directory")
    root.mkdir(parents=True, exist_ok=True)

    folder = root / "Panoptes" / "Asks"
    folder.mkdir(parents=True, exist_ok=True)

    ask_id = str(lead.get("ask_id") or "manual")
    username = str(lead.get("username") or "unknown")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    filename = _safe(f"{stamp}-{username}-{ask_id}") + ".md"
    path = folder / filename

    quote = (lead.get("ask_quote") or lead.get("evidence") or "").strip()
    front = {
        "type": "panoptes-ask",
        "ask_id": ask_id,
        "username": username,
        "platform": lead.get("platform") or lead.get("ask_source") or "",
        "offer": offer,
        "silence_score": lead.get("silence_score"),
        "email": lead.get("email") or "",
        "phone": lead.get("phone") or "",
        "website": lead.get("website") or "",
        "url": lead.get("ask_url") or lead.get("profile_url") or "",
        "tags": ["panoptes", "demand", "ask"],
        "created": datetime.now(timezone.utc).isoformat(),
    }
    body = [
        f"# {username} — unanswered ask",
        "",
        "## Quote",
        "",
        f"> {quote}" if quote else "_No quote_",
        "",
        "## Context",
        "",
        f"- Platform: `{front['platform']}`",
        f"- Silence: `{front['silence_score']}`",
        f"- Offer: `{offer or 'n/a'}`",
        f"- Source: {front['url'] or 'n/a'}",
        "",
    ]
    if solution:
        body += [
            "## Solution",
            "",
            f"**Diagnosis:** {solution.get('diagnosis') or ''}",
            "",
            "### Steps",
            "",
        ]
        for i, step in enumerate(solution.get("steps") or [], 1):
            body.append(f"{i}. {step}")
        body += [
            "",
            f"**Deliverable:** {solution.get('deliverable') or ''}",
            "",
            f"**Draft:** {solution.get('draft') or solution.get('helpful_note') or ''}",
            "",
        ]
        if solution.get("profile"):
            body += ["## Profile", "", f"```json\n{_tiny_json(solution['profile'])}\n```", ""]
        if solution.get("account"):
            body += ["## Account", "", f"```json\n{_tiny_json(solution['account'])}\n```", ""]

    path.write_text(_frontmatter(front) + "\n".join(body), encoding="utf-8")
    return {"ok": True, "path": str(path), "connector": "obsidian", "filename": filename}


def export_brief(brief: dict[str, Any], *, offer: str = "") -> dict[str, Any]:
    root = vault_path()
    if root is None:
        raise ValueError("Set OBSIDIAN_VAULT_PATH to a valid vault directory")
    root.mkdir(parents=True, exist_ok=True)
    folder = root / "Panoptes" / "Briefs"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    filename = _safe(f"{stamp}-brief-{offer or 'demand'}") + ".md"
    path = folder / filename
    front = {
        "type": "panoptes-brief",
        "offer": offer,
        "demand_score": brief.get("demand_score"),
        "verdict": brief.get("verdict") or "",
        "tags": ["panoptes", "brief"],
        "created": datetime.now(timezone.utc).isoformat(),
    }
    pains = brief.get("top_pains") or []
    actions = brief.get("next_actions") or []
    body = [
        f"# Demand brief — {offer or 'open scan'}",
        "",
        f"**Verdict:** {front['verdict']}",
        f"**Score:** {front['demand_score']}",
        "",
        "## Reasoning",
        "",
        str(brief.get("reasoning") or ""),
        "",
        "## Voice of customer",
        "",
    ]
    for line in brief.get("voice_of_customer") or []:
        body.append(f"- {line}")
    body += ["", "## Top pains", ""]
    for pain in pains:
        body.append(f"- {pain}")
    body += ["", "## Next actions", ""]
    for action in actions:
        body.append(f"- {action}")
    path.write_text(_frontmatter(front) + "\n".join(body), encoding="utf-8")
    return {"ok": True, "path": str(path), "connector": "obsidian", "filename": filename}


def export_profile(profile: dict[str, Any]) -> dict[str, Any]:
    root = vault_path()
    if root is None:
        raise ValueError("Set OBSIDIAN_VAULT_PATH to a valid vault directory")
    root.mkdir(parents=True, exist_ok=True)
    folder = root / "Panoptes" / "Profiles"
    folder.mkdir(parents=True, exist_ok=True)
    name = profile.get("display_name") or profile.get("username") or "unknown"
    filename = _safe(f"{profile.get('profile_id') or name}") + ".md"
    path = folder / filename
    front = {
        "type": "panoptes-profile",
        "profile_id": profile.get("profile_id") or "",
        "display_name": name,
        "priority": profile.get("priority_score"),
        "identity_confidence": profile.get("identity_confidence"),
        "platforms": profile.get("platforms") or [],
        "tags": ["panoptes", "profile"],
        "created": datetime.now(timezone.utc).isoformat(),
    }
    routes = profile.get("contact", {}).get("routes") or []
    body = [
        f"# {name}",
        "",
        profile.get("summary") or "",
        "",
        "## Contact routes",
        "",
    ]
    for route in routes[:8]:
        body.append(f"- `{route.get('channel')}` · {route.get('value')} · quality {route.get('quality')}")
    body += ["", "## Risks", ""]
    for risk in profile.get("risk_flags") or []:
        body.append(f"- {risk}")
    body += ["", "## Evidence", ""]
    for ev in profile.get("evidence") or []:
        body.append(f"- ({ev.get('platform')}) {ev.get('quote')}")
    path.write_text(_frontmatter(front) + "\n".join(body), encoding="utf-8")
    return {"ok": True, "path": str(path), "connector": "obsidian", "filename": filename}


def _frontmatter(data: dict[str, Any]) -> str:
    lines = ["---"]
    for key, value in data.items():
        if isinstance(value, list):
            lines.append(f"{key}: [{', '.join(_yaml_scalar(v) for v in value)}]")
        elif value is None:
            lines.append(f"{key}: null")
        else:
            lines.append(f"{key}: {_yaml_scalar(value)}")
    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def _yaml_scalar(value: Any) -> str:
    text = str(value)
    if re.search(r'[:#\[\]\{\},\n"\']', text) or text == "":
        return '"' + text.replace('"', '\\"') + '"'
    return text


def _safe(value: str) -> str:
    value = re.sub(r"[^\w.\-]+", "-", value.strip())
    return value.strip("-")[:120] or "note"


def _tiny_json(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, indent=2)[:4000]
