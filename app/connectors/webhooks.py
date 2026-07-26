"""Webhook + API push adapters."""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.web.helpers import env_get


def post_json(url: str, payload: dict[str, Any], *, headers: dict[str, str] | None = None) -> dict[str, Any]:
    if not url:
        raise ValueError("Webhook URL missing")
    with httpx.Client(timeout=20.0) as client:
        response = client.post(url, json=payload, headers=headers or {"Content-Type": "application/json"})
    return {
        "ok": 200 <= response.status_code < 300,
        "status_code": response.status_code,
        "body": (response.text or "")[:500],
    }


def push_slack(event: str, data: dict[str, Any]) -> dict[str, Any]:
    url = env_get("SLACK_WEBHOOK_URL")
    text = _summary(event, data)
    result = post_json(url, {"text": text, "blocks": _slack_blocks(event, data)})
    result["connector"] = "slack"
    return result


def push_discord(event: str, data: dict[str, Any]) -> dict[str, Any]:
    url = env_get("DISCORD_WEBHOOK_URL")
    result = post_json(url, {
        "content": _summary(event, data)[:1900],
        "embeds": [{
            "title": f"Panoptes · {event}",
            "description": _summary(event, data)[:3500],
            "color": 0x35E6FF,
        }],
    })
    result["connector"] = "discord"
    return result


def push_zapier(event: str, data: dict[str, Any]) -> dict[str, Any]:
    url = env_get("ZAPIER_WEBHOOK_URL")
    result = post_json(url, {"source": "panoptes", "event": event, "data": data})
    result["connector"] = "zapier"
    return result


def push_make(event: str, data: dict[str, Any]) -> dict[str, Any]:
    url = env_get("MAKE_WEBHOOK_URL")
    result = post_json(url, {"source": "panoptes", "event": event, "data": data})
    result["connector"] = "make"
    return result


def push_hubspot(event: str, data: dict[str, Any]) -> dict[str, Any]:
    url = env_get("HUBSPOT_WEBHOOK_URL")
    result = post_json(url, {"source": "panoptes", "event": event, "data": data})
    result["connector"] = "hubspot"
    return result


def push_generic(event: str, data: dict[str, Any]) -> dict[str, Any]:
    url = env_get("PANOPTES_GENERIC_WEBHOOK_URL")
    result = post_json(url, {"source": "panoptes", "event": event, "data": data})
    result["connector"] = "webhook"
    return result


def push_notion(event: str, data: dict[str, Any]) -> dict[str, Any]:
    token = env_get("NOTION_API_KEY")
    database_id = env_get("NOTION_DATABASE_ID")
    if not token or not database_id:
        raise ValueError("NOTION_API_KEY and NOTION_DATABASE_ID required")

    title = _title(event, data)
    props = {
        "Name": {"title": [{"text": {"content": title[:200]}}]},
    }
    # Soft optional properties — Notion ignores unknown names only if schema matches;
    # keep minimal Name title so any database works.
    children = [{
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [{"type": "text", "text": {"content": _summary(event, data)[:1900]}}],
        },
    }, {
        "object": "block",
        "type": "code",
        "code": {
            "language": "json",
            "rich_text": [{"type": "text", "text": {"content": json.dumps(data, ensure_ascii=False)[:1800]}}],
        },
    }]
    payload = {
        "parent": {"database_id": database_id},
        "properties": props,
        "children": children,
    }
    with httpx.Client(timeout=25.0) as client:
        response = client.post(
            "https://api.notion.com/v1/pages",
            headers={
                "Authorization": f"Bearer {token}",
                "Notion-Version": "2022-06-28",
                "Content-Type": "application/json",
            },
            json=payload,
        )
    return {
        "ok": 200 <= response.status_code < 300,
        "status_code": response.status_code,
        "body": (response.text or "")[:500],
        "connector": "notion",
    }


def push_linear(event: str, data: dict[str, Any]) -> dict[str, Any]:
    token = env_get("LINEAR_API_KEY")
    team_id = env_get("LINEAR_TEAM_ID")
    if not token or not team_id:
        raise ValueError("LINEAR_API_KEY and LINEAR_TEAM_ID required")

    title = _title(event, data)[:180]
    description = _summary(event, data) + "\n\n```json\n" + json.dumps(data, ensure_ascii=False)[:3000] + "\n```"
    query = """
    mutation IssueCreate($input: IssueCreateInput!) {
      issueCreate(input: $input) {
        success
        issue { id identifier url }
      }
    }
    """
    with httpx.Client(timeout=25.0) as client:
        response = client.post(
            "https://api.linear.app/graphql",
            headers={
                "Authorization": token,
                "Content-Type": "application/json",
            },
            json={
                "query": query,
                "variables": {
                    "input": {
                        "teamId": team_id,
                        "title": title,
                        "description": description,
                    }
                },
            },
        )
    return {
        "ok": 200 <= response.status_code < 300,
        "status_code": response.status_code,
        "body": (response.text or "")[:700],
        "connector": "linear",
    }


def _title(event: str, data: dict[str, Any]) -> str:
    lead = data.get("lead") or data
    username = lead.get("username") or data.get("username") or "ask"
    quote = (lead.get("ask_quote") or data.get("ask_quote") or event)[:80]
    return f"[{event}] {username}: {quote}"


def _summary(event: str, data: dict[str, Any]) -> str:
    lead = data.get("lead") or {}
    solution = data.get("solution") or {}
    parts = [f"Panoptes event `{event}`"]
    if lead.get("username"):
        parts.append(f"@{lead['username']}")
    if lead.get("ask_quote"):
        parts.append(f"“{str(lead['ask_quote'])[:160]}”")
    if solution.get("diagnosis"):
        parts.append(f"Diagnosis: {solution['diagnosis']}")
    if data.get("insight"):
        parts.append(str(data["insight"]))
    if data.get("verdict"):
        parts.append(f"Verdict: {data['verdict']}")
    return " · ".join(parts)


def _slack_blocks(event: str, data: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"Panoptes · {event}"[:140]},
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": _summary(event, data)[:2900]},
        },
    ]
