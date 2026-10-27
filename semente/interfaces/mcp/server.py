"""MCP wrapper for a remote A2A agent: the whole agent exposed as ONE MCP tool.

``semente mcp --url http://localhost:3000`` starts a stdio MCP server (for
Claude Desktop, Cursor, ...) with a single tool that forwards the question to
the agent's A2A endpoint (``POST /a2a``, ``message/send``) and returns its
text reply. Works with any A2A agent, not only Semente apps.
"""

from __future__ import annotations

import os
import re
from typing import Any, Optional
from uuid import uuid4

import httpx

CARD_PATH = "/.well-known/agent-card.json"
RPC_PATH = "/a2a"


class A2AClientError(RuntimeError):
    """The remote agent could not be reached or answered with an error."""


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _headers(api_key: Optional[str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


def fetch_card(base_url: str, timeout: float = 10.0) -> dict[str, Any]:
    """Best-effort Agent Card fetch (``{}`` when unreachable)."""
    try:
        resp = httpx.get(base_url.rstrip("/") + CARD_PATH, timeout=timeout)
        resp.raise_for_status()
        card = resp.json()
        return card if isinstance(card, dict) else {}
    except (httpx.HTTPError, ValueError):
        return {}


async def send_message(
    base_url: str,
    text: str,
    context_id: str,
    api_key: Optional[str] = None,
    rpc_url: Optional[str] = None,
    timeout: float = 120.0,
) -> str:
    """A2A ``message/send``; returns the agent's text reply."""
    payload = {
        "jsonrpc": "2.0",
        "id": str(uuid4()),
        "method": "message/send",
        "params": {
            "message": {
                "kind": "message",
                "role": "user",
                "messageId": str(uuid4()),
                "contextId": context_id,
                "parts": [{"kind": "text", "text": text}],
            }
        },
    }
    url = rpc_url or base_url.rstrip("/") + RPC_PATH
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload, headers=_headers(api_key))
    except httpx.HTTPError as exc:
        raise A2AClientError(f"Could not reach the A2A agent at {url}: {exc}") from exc

    if resp.status_code in (401, 403):
        raise A2AClientError("The A2A agent rejected the credentials (set --api-key / A2A_API_KEY).")
    try:
        body = resp.json()
    except ValueError as exc:
        raise A2AClientError(f"Invalid response from the A2A agent (HTTP {resp.status_code}).") from exc

    if "error" in body:
        err = body["error"] or {}
        raise A2AClientError(f"A2A error {err.get('code')}: {err.get('message')}")

    result = body.get("result") or {}
    # A message result carries parts directly; a task result carries them in status.message.
    message = result if "parts" in result else (result.get("status") or {}).get("message") or {}
    texts = [
        p["text"]
        for p in message.get("parts") or []
        if isinstance(p, dict) and isinstance(p.get("text"), str)
    ]
    return "\n".join(texts) if texts else ""


def build_server(
    url: str,
    name: Optional[str] = None,
    api_key: Optional[str] = None,
    timeout: float = 120.0,
):
    """Builds the FastMCP server exposing the A2A agent at ``url`` as one tool."""
    from mcp.server.fastmcp import FastMCP  # optional dependency: semente[mcp]

    api_key = api_key or os.getenv("A2A_API_KEY") or None
    card = fetch_card(url)
    agent_name = name or card.get("name") or "agent"
    tool_name = f"ask_{_slug(agent_name)}" or "ask"
    description = (
        f"Ask the '{agent_name}' agent a question (A2A). "
        + (card.get("description") or "")
        + " Send the full question in `message`; the conversation continues "
        "across calls."
    ).strip()
    skills = [s.get("name") or s.get("id") for s in card.get("skills") or [] if isinstance(s, dict)]
    if skills:
        description += " Skills: " + ", ".join(str(s) for s in skills if s) + "."

    server = FastMCP(_slug(agent_name) or "semente-a2a")
    default_context = str(uuid4())  # one conversation per MCP server process

    async def ask(message: str, context_id: Optional[str] = None) -> str:
        """Placeholder docstring, replaced by the card description."""
        reply = await send_message(
            url, message, context_id or default_context, api_key=api_key, timeout=timeout
        )
        return reply or "(the agent returned no text)"

    server.add_tool(ask, name=tool_name, description=description)
    return server


def run_stdio(url: str, name: Optional[str] = None, api_key: Optional[str] = None) -> None:
    build_server(url, name=name, api_key=api_key).run(transport="stdio")
