"""Connector catalog + readiness."""

from __future__ import annotations

from typing import Any

from app.web.helpers import ROOT, env_get


def connector_catalog() -> list[dict[str, Any]]:
    return [
        {
            "id": "mcp",
            "name": "Claude / Cursor MCP",
            "kind": "mcp",
            "description": "Expose Panoptes tools to Claude Desktop, Cursor, and any MCP host over stdio.",
            "setup": "Run panoptes_mcp.py and paste the generated config into Claude or Cursor.",
            "env": [],
            "docs": "https://modelcontextprotocol.io",
        },
        {
            "id": "obsidian",
            "name": "Obsidian",
            "kind": "vault",
            "description": "Write ask dossiers, briefs, and profile notes into a local Obsidian vault.",
            "setup": "Set OBSIDIAN_VAULT_PATH to your vault root.",
            "env": ["OBSIDIAN_VAULT_PATH"],
            "docs": "https://obsidian.md",
        },
        {
            "id": "slack",
            "name": "Slack",
            "kind": "webhook",
            "description": "Push demand alerts and solution cards to a Slack channel.",
            "setup": "Create an Incoming Webhook and set SLACK_WEBHOOK_URL.",
            "env": ["SLACK_WEBHOOK_URL"],
            "docs": "https://api.slack.com/messaging/webhooks",
        },
        {
            "id": "discord",
            "name": "Discord",
            "kind": "webhook",
            "description": "Post radar hits and AI briefs into Discord.",
            "setup": "Create a channel webhook and set DISCORD_WEBHOOK_URL.",
            "env": ["DISCORD_WEBHOOK_URL"],
            "docs": "https://discord.com/developers/docs/resources/webhook",
        },
        {
            "id": "zapier",
            "name": "Zapier",
            "kind": "webhook",
            "description": "Catch Panoptes events and fan out to 6,000+ apps.",
            "setup": "Create a Catch Hook Zap and set ZAPIER_WEBHOOK_URL.",
            "env": ["ZAPIER_WEBHOOK_URL"],
            "docs": "https://zapier.com/apps/webhook/integrations",
        },
        {
            "id": "make",
            "name": "Make",
            "kind": "webhook",
            "description": "Trigger Make scenarios from radar or AI events.",
            "setup": "Add a Custom Webhook module and set MAKE_WEBHOOK_URL.",
            "env": ["MAKE_WEBHOOK_URL"],
            "docs": "https://www.make.com/en/help/tools/webhooks",
        },
        {
            "id": "notion",
            "name": "Notion",
            "kind": "api",
            "description": "Create database rows for asks, contacts, and solution notes.",
            "setup": "Create an integration, share a database, set NOTION_API_KEY + NOTION_DATABASE_ID.",
            "env": ["NOTION_API_KEY", "NOTION_DATABASE_ID"],
            "docs": "https://developers.notion.com",
        },
        {
            "id": "linear",
            "name": "Linear",
            "kind": "api",
            "description": "Open follow-up issues from unanswered demand.",
            "setup": "Create a personal API key and set LINEAR_API_KEY + LINEAR_TEAM_ID.",
            "env": ["LINEAR_API_KEY", "LINEAR_TEAM_ID"],
            "docs": "https://developers.linear.app/docs",
        },
        {
            "id": "hubspot",
            "name": "HubSpot",
            "kind": "webhook",
            "description": "Forward contactable asks into HubSpot workflows via webhook.",
            "setup": "Set HUBSPOT_WEBHOOK_URL to a workflow webhook URL.",
            "env": ["HUBSPOT_WEBHOOK_URL"],
            "docs": "https://developers.hubspot.com",
        },
        {
            "id": "webhook",
            "name": "Generic webhook",
            "kind": "webhook",
            "description": "POST JSON to any endpoint (n8n, Relay, custom CRM, etc.).",
            "setup": "Set PANOPTES_GENERIC_WEBHOOK_URL.",
            "env": ["PANOPTES_GENERIC_WEBHOOK_URL"],
            "docs": "",
        },
    ]


def connector_status() -> dict[str, Any]:
    items = []
    for item in connector_catalog():
        ready = True
        missing = []
        for key in item["env"]:
            if not env_get(key):
                ready = False
                missing.append(key)
        if item["id"] == "mcp":
            ready = True
            missing = []
        items.append({
            **item,
            "ready": ready,
            "missing": missing,
        })
    return {
        "connectors": items,
        "ready_count": sum(1 for i in items if i["ready"]),
        "mcp_entry": str((ROOT / "panoptes_mcp.py").resolve()),
        "repo_root": str(ROOT.resolve()),
    }
