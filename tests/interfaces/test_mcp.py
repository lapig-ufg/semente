"""Tests of the MCP wrapper: a remote A2A agent exposed as ONE MCP tool."""

import asyncio
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

pytest.importorskip("mcp")

from semente.interfaces.a2a import A2A  # noqa: E402
from semente.interfaces.mcp import A2AClientError, build_server, send_message  # noqa: E402
from semente.interfaces.mcp import server as mcp_server  # noqa: E402

BASE = "http://agent.test"
REAL_ASYNC_CLIENT = httpx.AsyncClient


class FakeHarness:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def run(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(content=f"echo: {kwargs['input']}")


@pytest.fixture
def remote(monkeypatch):
    """An in-process A2A agent reachable at BASE through the wrapper's httpx calls."""
    harness = FakeHarness()
    app = FastAPI()
    card = {
        "description": "Docs helper",
        "skills": [{"id": "qa", "name": "Docs Q&A", "description": "answers"}],
    }
    app.include_router(A2A(agent=harness, name="Groot Bot", card=card, **{"api_key": None}).get_router())
    sync = TestClient(app, base_url=BASE)

    monkeypatch.setattr(mcp_server.httpx, "get", lambda url, **kw: sync.get(url.replace(BASE, "")))
    monkeypatch.setattr(
        mcp_server.httpx,
        "AsyncClient",
        lambda **kw: REAL_ASYNC_CLIENT(transport=httpx.ASGITransport(app=app), **kw),
    )
    return harness


def test_exposes_exactly_one_tool_named_after_the_card(remote):
    server = build_server(BASE)
    tools = asyncio.run(server.list_tools())

    assert [t.name for t in tools] == ["ask_groot_bot"]
    assert "Docs helper" in tools[0].description
    assert "Docs Q&A" in tools[0].description


def test_tool_forwards_the_question_and_keeps_the_conversation(remote):
    server = build_server(BASE)

    first = asyncio.run(server.call_tool("ask_groot_bot", {"message": "hi"}))
    asyncio.run(server.call_tool("ask_groot_bot", {"message": "again"}))

    assert "echo: hi" in str(first)
    assert remote.calls[0]["input"] == "hi"
    # Same context -> same Semente session for both calls.
    assert remote.calls[0]["session_id"] == remote.calls[1]["session_id"]


def test_context_id_can_be_overridden(remote):
    server = build_server(BASE)
    asyncio.run(server.call_tool("ask_groot_bot", {"message": "x", "context_id": "other"}))

    assert remote.calls[0]["session_id"] == "a2a:other"


def test_name_option_overrides_the_card_name(remote):
    server = build_server(BASE, name="Docs Bot")
    assert [t.name for t in asyncio.run(server.list_tools())] == ["ask_docs_bot"]


def test_unreachable_card_falls_back_to_generic_name(monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(mcp_server.httpx, "get", boom)
    server = build_server(BASE)
    assert [t.name for t in asyncio.run(server.list_tools())] == ["ask_agent"]


def test_send_message_reports_a2a_errors(remote):
    # tasks/get is unsupported, but an unknown message part still reaches the agent;
    # use an invalid message to provoke an A2A error from the server.
    async def run():
        # Empty text -> invalid params (-32602) from the A2A channel.
        return await send_message(BASE, "   ", "ctx")

    with pytest.raises(A2AClientError, match="A2A error"):
        asyncio.run(run())


def test_send_message_rejects_bad_credentials(monkeypatch):
    app = FastAPI()
    app.include_router(A2A(agent=FakeHarness(), name="g", api_key="secret").get_router())
    monkeypatch.setattr(
        mcp_server.httpx,
        "AsyncClient",
        lambda **kw: REAL_ASYNC_CLIENT(transport=httpx.ASGITransport(app=app), **kw),
    )

    with pytest.raises(A2AClientError, match="credentials"):
        asyncio.run(send_message(BASE, "hi", "ctx", api_key="wrong"))
    assert asyncio.run(send_message(BASE, "hi", "ctx", api_key="secret")) == "echo: hi"
