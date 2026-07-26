"""Unified push dispatcher."""

from __future__ import annotations

from typing import Any, Callable

from app.connectors import obsidian, webhooks
from app.connectors.registry import connector_status


HANDLERS: dict[str, Callable[[str, dict[str, Any]], dict[str, Any]]] = {
    "slack": webhooks.push_slack,
    "discord": webhooks.push_discord,
    "zapier": webhooks.push_zapier,
    "make": webhooks.push_make,
    "hubspot": webhooks.push_hubspot,
    "webhook": webhooks.push_generic,
    "notion": webhooks.push_notion,
    "linear": webhooks.push_linear,
}


def push_payload(
    connector: str,
    event: str,
    data: dict[str, Any],
    *,
    offer: str = "",
) -> dict[str, Any]:
    connector = (connector or "").lower().strip()
    if connector == "mcp":
        return {
            "ok": True,
            "connector": "mcp",
            "message": "MCP is a pull protocol — connect Claude/Cursor via panoptes_mcp.py",
            "config": mcp_client_configs(),
        }

    if connector == "obsidian":
        kind = (data.get("kind") or event or "ask").lower()
        if kind in ("brief", "demand_brief"):
            return obsidian.export_brief(data.get("brief") or data, offer=offer)
        if kind in ("profile", "profiles"):
            return obsidian.export_profile(data.get("profile") or data)
        lead = data.get("lead") or data
        return obsidian.export_ask(lead, offer=offer, solution=data.get("solution"))

    handler = HANDLERS.get(connector)
    if not handler:
        raise ValueError(f"Unknown connector: {connector}")
    return handler(event, data)


def mcp_client_configs() -> dict[str, Any]:
    import sys

    status = connector_status()
    entry = status["mcp_entry"]
    root = status["repo_root"]
    python = sys.executable or "python"
    return {
        "claude_desktop": {
            "mcpServers": {
                "panoptes": {
                    "command": python,
                    "args": [entry],
                    "cwd": root,
                    "env": {},
                }
            }
        },
        "cursor": {
            "mcpServers": {
                "panoptes": {
                    "command": python,
                    "args": [entry],
                    "cwd": root,
                }
            }
        },
        "claude_cli": f"claude mcp add panoptes -- {python} {entry}",
        "notes": [
            "Claude Desktop: paste claude_desktop into claude_desktop_config.json",
            "Cursor: paste cursor into .cursor/mcp.json or Cursor Settings → MCP",
            "Restart the host after saving config",
        ],
    }
