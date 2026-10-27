"""Tests of the A2A (Agent2Agent) channel: Agent Card + JSON-RPC message/send."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from semente.interfaces.a2a import A2A
from semente.manifest import Manifest


class FakeHarness:
    """Records calls and echoes the text back, like a trivial agent."""

    def __init__(self, fail: bool = False) -> None:
        self.calls: list[dict] = []
        self.fail = fail

    def run(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("boom")
        return SimpleNamespace(content=f"echo: {kwargs['input']}")


def _client(harness=None, **kwargs) -> tuple[TestClient, FakeHarness]:
    harness = harness or FakeHarness()
    app = FastAPI()
    app.include_router(A2A(agent=harness, name="groot", **kwargs).get_router())
    return TestClient(app), harness


def _send(client: TestClient, text="hello", context_id=None, headers=None, **extra):
    message = {"role": "user", "kind": "message", "messageId": "m1", "parts": [{"kind": "text", "text": text}]}
    if context_id:
        message["contextId"] = context_id
    body = {"jsonrpc": "2.0", "id": 7, "method": "message/send", "params": {"message": message}, **extra}
    return client.post("/a2a", json=body, headers=headers)


# ---------------------------------------------------------------- Agent Card
def test_agent_card_describes_the_agent():
    client, _ = _client(card={"description": "Docs helper", "version": "9.9"})
    card = client.get("/.well-known/agent-card.json").json()

    assert card["name"] == "groot"
    assert card["description"] == "Docs helper"
    assert card["version"] == "9.9"
    assert card["protocolVersion"] == "0.3.0"
    assert card["url"].endswith("/a2a")
    assert card["capabilities"] == {"streaming": False, "pushNotifications": False}
    assert card["skills"] and card["skills"][0]["id"] == "chat"
    assert "securitySchemes" not in card


def test_agent_card_legacy_path_and_custom_skills_and_public_url():
    skills = [{"id": "docs", "name": "Docs", "description": "d", "tags": ["x"]}]
    client, _ = _client(card={"skills": skills}, public_url="https://groot.example.org/")

    card = client.get("/.well-known/agent.json").json()
    assert card["skills"] == skills
    assert card["url"] == "https://groot.example.org/a2a"


# --------------------------------------------------------------- message/send
def test_message_send_returns_an_agent_message_and_keeps_the_context():
    client, harness = _client()

    first = _send(client, "what is semente?").json()
    result = first["result"]
    assert first["id"] == 7 and result["kind"] == "message" and result["role"] == "agent"
    assert result["parts"] == [{"kind": "text", "text": "echo: what is semente?"}]
    context_id = result["contextId"]

    _send(client, "and the manifest?", context_id=context_id)
    assert harness.calls[0]["session_id"] == harness.calls[1]["session_id"] == f"a2a:{context_id}"
    assert harness.calls[1]["user_id"] == f"a2a:{context_id}"


def test_message_send_without_context_creates_distinct_conversations():
    client, harness = _client()
    _send(client)
    _send(client)
    assert harness.calls[0]["session_id"] != harness.calls[1]["session_id"]


def test_message_send_joins_text_parts_and_ignores_other_parts():
    client, harness = _client()
    body = {
        "jsonrpc": "2.0", "id": 1, "method": "message/send",
        "params": {"message": {"role": "user", "parts": [
            {"kind": "text", "text": "line one"},
            {"kind": "file", "file": {"uri": "x"}},
            {"kind": "text", "text": "line two"},
        ]}},
    }
    client.post("/a2a", json=body)
    assert harness.calls[0]["input"] == "line one\nline two"


# ------------------------------------------------------------------- errors
@pytest.mark.parametrize(
    "payload, code",
    [
        ({"jsonrpc": "2.0", "id": 1, "method": "message/send", "params": {}}, -32602),
        ({"jsonrpc": "2.0", "id": 1, "method": "message/send",
          "params": {"message": {"parts": [{"kind": "file", "file": {}}]}}}, -32602),
        ({"jsonrpc": "2.0", "id": 1, "method": "nope"}, -32601),
        ({"jsonrpc": "2.0", "id": 1, "method": "message/stream", "params": {}}, -32004),
        ({"jsonrpc": "2.0", "id": 1, "method": "tasks/get", "params": {"id": "t"}}, -32001),
        ({"id": 1, "method": "message/send"}, -32600),
    ],
)
def test_jsonrpc_errors(payload, code):
    client, _ = _client()
    assert client.post("/a2a", json=payload).json()["error"]["code"] == code


def test_invalid_json_is_a_parse_error():
    client, _ = _client()
    response = client.post("/a2a", content=b"{not json", headers={"content-type": "application/json"})
    assert response.json()["error"]["code"] == -32700


def test_harness_failure_becomes_internal_error_without_leaking_details():
    client, _ = _client(harness=FakeHarness(fail=True))
    error = _send(client).json()["error"]
    assert error["code"] == -32603 and "boom" not in error["message"]


# --------------------------------------------------------------------- auth
def test_api_key_is_enforced_when_configured():
    client, harness = _client(api_key="s3cret")

    assert _send(client).status_code == 401
    assert _send(client, headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert _send(client, headers={"Authorization": "Bearer s3cret"}).json()["result"]["role"] == "agent"
    assert _send(client, headers={"X-API-Key": "s3cret"}).json()["result"]["role"] == "agent"
    assert len(harness.calls) == 2  # the rejected calls never reached the agent

    card = client.get("/.well-known/agent-card.json").json()  # discovery stays open
    assert card["security"] == [{"bearer": []}] and "bearer" in card["securitySchemes"]


# ----------------------------------------------------------------- manifest
def test_manifest_a2a_block_round_trips(tmp_path):
    path = tmp_path / "semente.yaml"
    path.write_text(
        "name: groot\nchannels: [streamlit, a2a]\na2a:\n  description: Docs helper\n  version: '1.0'\n",
        encoding="utf-8",
    )
    manifest = Manifest.load(path)
    assert manifest.a2a == {"description": "Docs helper", "version": "1.0"}

    manifest.save(path)
    assert Manifest.load(path).a2a == manifest.a2a
    assert Manifest(name="x").a2a == {}
