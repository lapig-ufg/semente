"""A2A server channel: Agent Card + JSON-RPC ``message/send`` over the Harness."""

from __future__ import annotations

import hmac
import os
from importlib import metadata
from typing import Any, Optional
from uuid import uuid4

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from semente.logging import log_error, log_info

PROTOCOL_VERSION = "0.3.0"
RPC_PATH = "/a2a"

# JSON-RPC 2.0 + A2A error codes.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
TASK_NOT_FOUND = -32001
UNSUPPORTED_OPERATION = -32004


def _version() -> str:
    try:
        return metadata.version("semente-agents")
    except metadata.PackageNotFoundError:  # running from a source checkout
        return "0.0.0"


def _error(request_id: Any, code: int, message: str, status: int = 200) -> JSONResponse:
    return JSONResponse(
        {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}},
        status_code=status,
    )


def _text_of(message: dict[str, Any]) -> str:
    """Join the text parts of an A2A message (non-text parts are ignored)."""
    parts = message.get("parts") or []
    texts = [
        p["text"]
        for p in parts
        if isinstance(p, dict) and p.get("kind", "text") == "text" and isinstance(p.get("text"), str)
    ]
    return "\n".join(t for t in texts if t.strip())


class A2A:
    """Builds the FastAPI router that serves the app over A2A.

    Args:
        agent: The ``Harness`` (anything with ``run(user_id=, session_id=, input=)``
            returning an object with a ``content`` string).
        name: Agent name for the card (the manifest name).
        card: Optional ``manifest.a2a`` block: ``description``, ``version`` and
            ``skills``.
        api_key: Bearer key; defaults to the ``A2A_API_KEY`` env var. ``None``
            or empty disables auth.
        public_url: Externally reachable base URL; defaults to ``A2A_PUBLIC_URL``
            or, when unset, the URL the request came in on.
    """

    def __init__(
        self,
        agent: Any,
        name: str,
        card: Optional[dict[str, Any]] = None,
        api_key: Optional[str] = None,
        public_url: Optional[str] = None,
    ) -> None:
        self.agent = agent
        self.name = name
        self.card_config = card or {}
        self.api_key = api_key if api_key is not None else os.getenv("A2A_API_KEY") or None
        self.public_url = (public_url or os.getenv("A2A_PUBLIC_URL") or "").rstrip("/") or None

    # ------------------------------------------------------------------
    # Agent Card
    # ------------------------------------------------------------------
    def agent_card(self, base_url: str) -> dict[str, Any]:
        base = self.public_url or base_url.rstrip("/")
        description = self.card_config.get("description") or f"{self.name} — an AI agent built with Semente."
        skills = self.card_config.get("skills") or [
            {
                "id": "chat",
                "name": "Chat",
                "description": description,
                "tags": ["semente", "chat"],
            }
        ]
        card: dict[str, Any] = {
            "protocolVersion": PROTOCOL_VERSION,
            "name": self.name,
            "description": description,
            "url": f"{base}{RPC_PATH}",
            "preferredTransport": "JSONRPC",
            "version": str(self.card_config.get("version") or _version()),
            "capabilities": {"streaming": False, "pushNotifications": False},
            "defaultInputModes": ["text/plain"],
            "defaultOutputModes": ["text/plain"],
            "skills": skills,
        }
        if self.api_key:
            card["securitySchemes"] = {"bearer": {"type": "http", "scheme": "bearer"}}
            card["security"] = [{"bearer": []}]
        return card

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------
    def _authorized(self, request: Request) -> bool:
        if not self.api_key:
            return True
        header = request.headers.get("authorization", "")
        supplied = header[7:] if header.lower().startswith("bearer ") else request.headers.get("x-api-key", "")
        return hmac.compare_digest(supplied.encode(), self.api_key.encode())

    # ------------------------------------------------------------------
    # JSON-RPC
    # ------------------------------------------------------------------
    async def _handle_rpc(self, request: Request) -> JSONResponse:
        if not self._authorized(request):
            return _error(None, INVALID_REQUEST, "Unauthorized: missing or invalid API key.", status=401)

        try:
            body = await request.json()
        except Exception:
            return _error(None, PARSE_ERROR, "Parse error: the body is not valid JSON.")

        if not isinstance(body, dict) or body.get("jsonrpc") != "2.0" or not isinstance(body.get("method"), str):
            return _error(
                body.get("id") if isinstance(body, dict) else None,
                INVALID_REQUEST,
                "Invalid request: expected a JSON-RPC 2.0 object with a 'method'.",
            )

        request_id = body.get("id")
        method = body["method"]
        params = body.get("params")

        if method == "message/send":
            return await self._message_send(request_id, params)
        if method == "message/stream":
            return _error(request_id, UNSUPPORTED_OPERATION, "Streaming is not supported; use message/send.")
        if method in ("tasks/get", "tasks/cancel", "tasks/resubscribe"):
            return _error(request_id, TASK_NOT_FOUND, "Task not found: this agent answers with messages, not tasks.")
        return _error(request_id, METHOD_NOT_FOUND, f"Method not found: {method}")

    async def _message_send(self, request_id: Any, params: Any) -> JSONResponse:
        message = params.get("message") if isinstance(params, dict) else None
        if not isinstance(message, dict):
            return _error(request_id, INVALID_PARAMS, "Invalid params: 'message' is required.")
        text = _text_of(message)
        if not text:
            return _error(request_id, INVALID_PARAMS, "Invalid params: the message needs at least one text part.")

        context_id = str(message.get("contextId") or uuid4())
        identity = f"a2a:{context_id}"
        try:
            output = await run_in_threadpool(
                self.agent.run, user_id=identity, session_id=identity, input=text
            )
        except Exception as exc:  # noqa: BLE001 — surface as a JSON-RPC error
            log_error(f"a2a: harness failed: {exc}")
            return _error(request_id, INTERNAL_ERROR, "Internal error while running the agent.")

        log_info(f"a2a: answered context {context_id}")
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "kind": "message",
                    "role": "agent",
                    "messageId": uuid4().hex,
                    "contextId": context_id,
                    "parts": [{"kind": "text", "text": getattr(output, "content", "") or ""}],
                },
            }
        )

    # ------------------------------------------------------------------
    # Router
    # ------------------------------------------------------------------
    def get_router(self) -> APIRouter:
        router = APIRouter(tags=["A2A"])

        async def card(request: Request) -> JSONResponse:
            return JSONResponse(self.agent_card(str(request.base_url)))

        router.add_api_route("/.well-known/agent-card.json", card, methods=["GET"])
        router.add_api_route("/.well-known/agent.json", card, methods=["GET"])  # legacy path
        router.add_api_route(RPC_PATH, self._handle_rpc, methods=["POST"])
        return router
