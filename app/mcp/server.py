"""Panoptes MCP stdio server for Claude Desktop, Cursor, and other MCP hosts."""

from __future__ import annotations

import json
import sys
import traceback
from typing import Any

from app.web.helpers import load_env

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "panoptes", "version": "1.0.0"}


TOOLS = [
    {
        "name": "panoptes_health",
        "description": "Health check for the local Panoptes demand intelligence engine.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "panoptes_list_asks",
        "description": "List stored unanswered asks with silence and contact fields.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 25},
                "offer": {"type": "string", "description": "Optional offer filter"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "panoptes_get_ask",
        "description": "Fetch one stored ask by ask_id.",
        "inputSchema": {
            "type": "object",
            "properties": {"ask_id": {"type": "string"}},
            "required": ["ask_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "panoptes_solve",
        "description": "Run the Answer Engine on an ask_id or freeform text.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ask_id": {"type": "string"},
                "text": {"type": "string"},
                "offer": {"type": "string"},
                "niche": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "panoptes_cockpit",
        "description": "Run the full AI cockpit over stored demand (match, personas, moat, profiles, accounts).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "offer": {"type": "string"},
                "limit": {"type": "integer", "minimum": 10, "maximum": 300, "default": 100},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "panoptes_profiles",
        "description": "Resolve cross-platform profile dossiers from stored asks.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
                "offer": {"type": "string"},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "panoptes_push",
        "description": "Push an event/payload to Obsidian, Slack, Discord, Notion, Linear, Zapier, Make, HubSpot, or a generic webhook.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "connector": {
                    "type": "string",
                    "enum": [
                        "obsidian", "slack", "discord", "notion", "linear",
                        "zapier", "make", "hubspot", "webhook",
                    ],
                },
                "event": {"type": "string"},
                "ask_id": {"type": "string"},
                "offer": {"type": "string"},
                "kind": {
                    "type": "string",
                    "description": "For Obsidian: ask | brief | profile",
                    "default": "ask",
                },
            },
            "required": ["connector"],
            "additionalProperties": False,
        },
    },
    {
        "name": "panoptes_connectors",
        "description": "Show connector readiness and MCP host config snippets.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
]


def main() -> None:
    load_env()
    stdin = sys.stdin.buffer
    while True:
        message = _read_message(stdin)
        if message is None:
            break
        if "method" in message and "id" not in message:
            continue
        response = handle(message)
        if response is not None:
            _write_message(response)


def _read_message(stdin) -> dict[str, Any] | None:
    headers: dict[str, str] = {}
    while True:
        line = stdin.readline()
        if not line:
            return None
        if line in (b"\n", b"\r\n"):
            break
        try:
            text = line.decode("utf-8").strip()
        except UnicodeDecodeError:
            continue
        if ":" not in text:
            # newline-delimited JSON fallback
            try:
                data = json.loads(text)
                return data if isinstance(data, dict) else None
            except json.JSONDecodeError:
                continue
        key, _, value = text.partition(":")
        headers[key.strip().lower()] = value.strip()

    length = int(headers.get("content-length") or "0")
    if length <= 0:
        return None
    body = stdin.read(length)
    if not body:
        return None
    data = json.loads(body.decode("utf-8"))
    return data if isinstance(data, dict) else None


def _write_message(payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    header = f"Content-Length: {len(body)}\r\n\r\n".encode("ascii")
    sys.stdout.buffer.write(header + body)
    sys.stdout.buffer.flush()


def handle(message: dict[str, Any]) -> dict[str, Any] | None:
    req_id = message.get("id")
    method = message.get("method")
    params = message.get("params") or {}
    try:
        if method == "initialize":
            return _ok(req_id, {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO,
                "instructions": (
                    "Panoptes Demand Radar MCP. Use panoptes_list_asks / panoptes_solve / "
                    "panoptes_cockpit for demand intelligence, and panoptes_push to send "
                    "results into Obsidian or ops tools."
                ),
            })
        if method == "ping":
            return _ok(req_id, {})
        if method == "tools/list":
            return _ok(req_id, {"tools": TOOLS})
        if method == "tools/call":
            name = params.get("name") or ""
            args = params.get("arguments") or {}
            result = call_tool(name, args if isinstance(args, dict) else {})
            return _ok(req_id, {
                "content": [{"type": "text", "text": _as_text(result)}],
                "structuredContent": result if isinstance(result, dict) else {"result": result},
                "isError": bool(isinstance(result, dict) and result.get("error")),
            })
        if method == "resources/list":
            return _ok(req_id, {"resources": []})
        if method == "prompts/list":
            return _ok(req_id, {"prompts": []})
        return _err(req_id, -32601, f"Method not found: {method}")
    except Exception as exc:  # noqa: BLE001 — surface tool failures to host
        if method == "tools/call":
            return _ok(req_id, {
                "content": [{
                    "type": "text",
                    "text": f"Error: {exc}\n{traceback.format_exc()[-1200:]}",
                }],
                "isError": True,
            })
        return _err(req_id, -32000, str(exc))


def call_tool(name: str, args: dict[str, Any]) -> Any:
    if name == "panoptes_health":
        from app import __version__
        from app.demand.store import list_leads

        return {
            "name": "Panoptes",
            "version": __version__,
            "asks_stored": len(list_leads(limit=500)),
            "ok": True,
        }

    if name == "panoptes_list_asks":
        leads = _leads(int(args.get("limit") or 25), str(args.get("offer") or ""))
        return {
            "count": len(leads),
            "asks": [_compact(lead) for lead in leads],
        }

    if name == "panoptes_get_ask":
        ask_id = str(args.get("ask_id") or "")
        lead = _find_ask(ask_id)
        if not lead:
            return {"error": "Ask not found", "ask_id": ask_id}
        return lead

    if name == "panoptes_solve":
        from app.ai.pipeline import solve_with_memory

        ask_id = str(args.get("ask_id") or "")
        text = str(args.get("text") or "").strip()
        offer = str(args.get("offer") or "")
        niche = str(args.get("niche") or "")
        corpus = _leads(500)
        lead = _find_ask(ask_id) if ask_id else None
        if lead is None and text:
            lead = {"ask_quote": text, "username": "manual", "ask_id": ""}
        if lead is None:
            return {"error": "Provide ask_id or text"}
        return solve_with_memory(lead, corpus, {"offer": offer, "niche": niche})

    if name == "panoptes_cockpit":
        from app.ai.pipeline import run_cockpit

        offer = str(args.get("offer") or "")
        limit = int(args.get("limit") or 100)
        return run_cockpit(_leads(limit, offer), {"offer": offer})

    if name == "panoptes_profiles":
        from app.ai.profiles import resolve_profiles

        offer = str(args.get("offer") or "")
        limit = int(args.get("limit") or 50)
        return resolve_profiles(_leads(limit, offer), limit=limit)

    if name == "panoptes_push":
        from app.connectors.push import push_payload

        connector = str(args.get("connector") or "")
        event = str(args.get("event") or "manual_push")
        offer = str(args.get("offer") or "")
        ask_id = str(args.get("ask_id") or "")
        kind = str(args.get("kind") or "ask")
        data: dict[str, Any] = {"kind": kind}
        if ask_id:
            lead = _find_ask(ask_id)
            if not lead:
                return {"error": "Ask not found", "ask_id": ask_id}
            data["lead"] = lead
            if connector == "obsidian" and kind == "ask":
                from app.ai.pipeline import solve_with_memory

                data["solution"] = solve_with_memory(lead, _leads(500), {"offer": offer})
        return push_payload(connector, event, data, offer=offer)

    if name == "panoptes_connectors":
        from app.connectors.push import mcp_client_configs
        from app.connectors.registry import connector_status

        return {**connector_status(), "configs": mcp_client_configs()}

    return {"error": f"Unknown tool: {name}"}


def _leads(limit: int, offer: str = "") -> list[dict[str, Any]]:
    from app.demand.store import list_leads

    capped = min(max(1, limit), 500)
    offer = (offer or "").strip()
    if offer:
        scoped = list_leads(limit=capped, offer=offer)
        if scoped:
            return scoped
    return list_leads(limit=capped)


def _find_ask(ask_id: str) -> dict[str, Any] | None:
    if not ask_id:
        return None
    for lead in _leads(500):
        if lead.get("ask_id") == ask_id:
            return lead
    return None


def _compact(lead: dict[str, Any]) -> dict[str, Any]:
    return {
        "ask_id": lead.get("ask_id"),
        "username": lead.get("username"),
        "platform": lead.get("platform") or lead.get("ask_source"),
        "silence_score": lead.get("silence_score"),
        "email": lead.get("email"),
        "phone": lead.get("phone"),
        "website": lead.get("website"),
        "ask_quote": (lead.get("ask_quote") or "")[:220],
        "ask_url": lead.get("ask_url"),
    }


def _as_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)[:120000]


def _ok(req_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _err(req_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


if __name__ == "__main__":
    main()
