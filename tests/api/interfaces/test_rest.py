"""Tests of the REST channel: runs, sessions, health and Bearer auth."""

import base64
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from semente.api.interfaces.rest import REST
from semente.tools.types import Audio, File, Image, Video

KEY = "test-key"
AUTH = {"Authorization": f"Bearer {KEY}"}


class FakeHarness:
    """Records run calls; echoes the text and any media it was given."""

    def __init__(self, store=None, fail: bool = False) -> None:
        self.calls: list[dict] = []
        self.store = store
        self.fail = fail

    def run(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("boom")
        return SimpleNamespace(
            content=f"echo: {kwargs['input']}",
            images=[Image(content=b"png", mime_type="image/png")],
            audio=None,
            videos=None,
            files=[File(content=b"pdf", mime_type="application/pdf", name="out.pdf")],
        )

    def sanitize(self, data):
        return data


class MemoryStore:
    """In-memory stand-in for ``SessionStore`` (same read/write contract)."""

    def __init__(self) -> None:
        self.records: dict[str, dict] = {}

    def get_record(self, user_id, session_id):
        record = self.records.get(session_id)
        if record is None:
            return None
        if user_id is not None and record["user_id"] != user_id:
            return None
        return dict(record)

    def get(self, user_id, session_id):
        record = self.get_record(user_id, session_id)
        if record is None:
            return None
        return {
            "session_state": record["session_state"],
            "runs": record["runs"],
            "interaction_assessment": record["interaction_assessment"],
        }

    def save(self, user_id, session_id, session_state, runs, interaction_assessment=None):
        self.records[session_id] = {
            "user_id": user_id,
            "session_id": session_id,
            "session_state": session_state,
            "runs": runs,
            "interaction_assessment": interaction_assessment,
        }


def _client(harness=None, api_key: str = KEY, store=None, **kwargs) -> tuple[TestClient, FakeHarness]:
    harness = harness or FakeHarness(store=store)
    app = FastAPI()
    app.include_router(REST(agent=harness, name="groot", api_key=api_key, **kwargs).get_router())
    return TestClient(app), harness


# ------------------------------------------------------------------- health
def test_health_is_public_and_reports_the_app():
    client, _ = _client()

    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["name"] == "groot"
    assert body["version"]


def test_health_works_even_without_a_configured_key():
    client, _ = _client(api_key="")

    assert client.get("/health").status_code == 200


# --------------------------------------------------------------------- auth
@pytest.mark.parametrize(
    "method,path,payload",
    [
        ("post", "/runs", {"message": "hi"}),
        ("get", "/sessions/s1/session", None),
        ("post", "/sessions/s1/session", {"user_id": "u1"}),
    ],
)
def test_protected_routes_require_a_bearer_token(method, path, payload):
    client, harness = _client(store=MemoryStore())

    response = getattr(client, method)(path, **({"json": payload} if payload else {}))

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert harness.calls == []


def test_wrong_or_non_bearer_token_is_rejected():
    client, _ = _client(store=MemoryStore())

    assert client.get("/health", headers={"Authorization": "Bearer nope"}).status_code == 200
    assert client.post("/runs", json={"message": "hi"}, headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.post("/runs", json={"message": "hi"}, headers={"Authorization": f"Basic {KEY}"}).status_code == 401


def test_missing_key_answers_503_instead_of_running_open():
    client, harness = _client(api_key="", store=MemoryStore())

    response = client.post("/runs", json={"message": "hi"}, headers=AUTH)

    assert response.status_code == 503
    assert "REST_API_KEY" in response.json()["detail"]
    assert harness.calls == []


# -------------------------------------------------------------------- /runs
def test_run_json_defaults_ids_and_returns_the_answer():
    client, harness = _client()

    response = client.post("/runs", json={"message": "olá"}, headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert body["content"] == "echo: olá"
    assert body["user_id"] == "rest:anonymous"
    assert body["session_id"].startswith("rest:rest:anonymous:")
    assert body["run_id"].startswith("run_")
    assert harness.calls[0]["user_id"] == "rest:anonymous"
    assert harness.calls[0]["session_id"] == body["session_id"]
    assert [i["base64"] for i in body["images"]] == [base64.b64encode(b"png").decode()]
    assert body["files"][0]["name"] == "out.pdf"
    assert body["audio"] == [] and body["videos"] == []


def test_run_json_forwards_explicit_ids():
    client, harness = _client()

    body = client.post(
        "/runs", json={"message": "oi", "user_id": "u1", "session_id": "s1"}, headers=AUTH
    ).json()

    assert (body["user_id"], body["session_id"]) == ("u1", "s1")
    assert harness.calls[0]["session_id"] == "s1"


def test_run_json_maps_base64_files_to_media_kwargs():
    client, harness = _client()
    payload = {
        "message": "look",
        "files": [
            {"name": "photo.png", "mime_type": "image/png", "data": base64.b64encode(b"img").decode()},
            {"name": "voice.ogg", "data": base64.b64encode(b"aud").decode()},
            {"name": "clip.mp4", "mime_type": "video/mp4", "data": base64.b64encode(b"vid").decode()},
            {"name": "report.pdf", "data": base64.b64encode(b"doc").decode()},
        ],
        "files_metadata": {"report.pdf": {"type": "document", "description": "annual report"}},
    }

    assert client.post("/runs", json=payload, headers=AUTH).status_code == 200
    kwargs = harness.calls[0]

    # type inferred from mime/extension when metadata is absent
    assert [i.content for i in kwargs["images"]] == [b"img"]
    assert [a.content for a in kwargs["audio"]] == [b"aud"]
    assert [v.content for v in kwargs["videos"]] == [b"vid"]
    assert [f.name for f in kwargs["files"]] == ["report.pdf"]
    assert isinstance(kwargs["files"][0], File)


def test_run_json_accepts_data_urls_and_url_only_files():
    client, harness = _client()
    payload = {
        "message": "x",
        "files": [
            {
                "name": "a.png",
                "type": "image",
                "data": "data:image/png;base64," + base64.b64encode(b"img").decode(),
            },
            {"name": "remote.png", "type": "image", "url": "https://example.org/a.png"},
        ],
    }

    assert client.post("/runs", json=payload, headers=AUTH).status_code == 200
    images = harness.calls[0]["images"]
    assert images[0].content == b"img"
    assert images[1].url == "https://example.org/a.png"


def test_run_multipart_accepts_typed_and_untyped_file_fields():
    client, harness = _client()

    response = client.post(
        "/runs",
        data={
            "message": "veja",
            "user_id": "u1",
            "files_metadata": json.dumps([{"name": "doc.pdf", "type": "document"}]),
        },
        files=[
            ("files", ("doc.pdf", b"%PDF", "application/pdf")),
            ("images", ("photo.png", b"img", "image/png")),
            ("audio", ("voice.ogg", b"aud", "audio/ogg")),
            ("videos", ("clip.mp4", b"vid", "video/mp4")),
        ],
        headers=AUTH,
    )

    assert response.status_code == 200
    kwargs = harness.calls[0]
    assert kwargs["input"] == "veja"
    assert [f.content for f in kwargs["files"]] == [b"%PDF"]
    assert [i.content for i in kwargs["images"]] == [b"img"]
    assert [a.content for a in kwargs["audio"]] == [b"aud"]
    assert [v.content for v in kwargs["videos"]] == [b"vid"]


def test_run_multipart_allows_a_file_only_turn():
    client, harness = _client()

    response = client.post(
        "/runs", files=[("images", ("photo.png", b"img", "image/png"))], headers=AUTH
    )

    assert response.status_code == 200
    assert harness.calls[0]["input"] == ""


def test_run_rejects_empty_turn_and_unsupported_content_type():
    client, harness = _client()

    assert client.post("/runs", json={"message": "  "}, headers=AUTH).status_code == 400
    assert (
        client.post(
            "/runs", content=b"x", headers={**AUTH, "Content-Type": "text/plain"}
        ).status_code
        == 415
    )
    assert harness.calls == []


def test_run_rejects_invalid_base64_and_metadata():
    client, _ = _client()

    bad_file = {"message": "x", "files": [{"name": "a.png", "data": "not base64!"}]}
    assert client.post("/runs", json=bad_file, headers=AUTH).status_code == 400

    bad_meta = {"message": "x", "files_metadata": "not json"}
    assert client.post("/runs", json=bad_meta, headers=AUTH).status_code == 400

    wrong_type = {"message": "x", "files_metadata": [{"type": "spreadsheet"}]}
    assert client.post("/runs", json=wrong_type, headers=AUTH).status_code == 422


def test_run_enforces_upload_limits():
    client, _ = _client(max_files=1, max_file_bytes=3)

    two_files = {
        "message": "x",
        "files": [
            {"name": "a.txt", "data": base64.b64encode(b"a").decode()},
            {"name": "b.txt", "data": base64.b64encode(b"b").decode()},
        ],
    }
    assert client.post("/runs", json=two_files, headers=AUTH).status_code == 413

    too_big = {"message": "x", "files": [{"name": "a.txt", "data": base64.b64encode(b"abcd").decode()}]}
    assert client.post("/runs", json=too_big, headers=AUTH).status_code == 413


def test_run_returns_500_without_leaking_the_error():
    client, _ = _client(harness=FakeHarness(fail=True))

    response = client.post("/runs", json={"message": "hi"}, headers=AUTH)

    assert response.status_code == 500
    assert "boom" not in response.json()["detail"]


# ---------------------------------------------------------------- sessions
def test_get_session_returns_the_stored_record():
    store = MemoryStore()
    store.save(
        "u1",
        "s1",
        session_state={"user_persona": {"name": "Ana"}},
        runs=[{"user": "hi", "assistant": "hello"}],
    )
    client, _ = _client(store=store)

    response = client.get("/sessions/s1/session", headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == "u1"
    assert body["session_id"] == "s1"
    assert body["session_state"]["user_persona"]["name"] == "Ana"
    assert body["runs"] == [{"user": "hi", "assistant": "hello"}]
    assert body["interaction_assessment"] is None


def test_get_session_scopes_by_user_and_404s_when_absent():
    store = MemoryStore()
    store.save("u1", "s1", session_state={}, runs=[])
    client, _ = _client(store=store)

    assert client.get("/sessions/s1/session?user_id=u2", headers=AUTH).status_code == 404
    assert client.get("/sessions/missing/session", headers=AUTH).status_code == 404
    assert client.get("/sessions/s1/session?user_id=u1", headers=AUTH).status_code == 200


def test_sessions_answer_503_without_a_store():
    client, _ = _client()

    assert client.get("/sessions/s1/session", headers=AUTH).status_code == 503
    assert (
        client.post("/sessions/s1/session", json={"user_id": "u1"}, headers=AUTH).status_code
        == 503
    )


def test_post_session_creates_then_deep_merges_state():
    store = MemoryStore()
    client, _ = _client(store=store)

    created = client.post(
        "/sessions/s1/session",
        json={"user_id": "u1", "session_state": {"a": {"x": 1}, "keep": True}},
        headers=AUTH,
    )
    assert created.status_code == 200
    assert created.json()["user_id"] == "u1"
    assert store.records["s1"]["session_state"] == {"a": {"x": 1}, "keep": True}

    updated = client.post(
        "/sessions/s1/session",
        json={"session_state": {"a": {"y": 2}}},
        headers=AUTH,
    ).json()
    assert updated["session_state"] == {"a": {"x": 1, "y": 2}, "keep": True}
    assert updated["user_id"] == "u1"  # owner is preserved


def test_post_session_replaces_runs_and_assessment():
    store = MemoryStore()
    store.save("u1", "s1", session_state={}, runs=[{"user": "old", "assistant": "old"}])
    client, _ = _client(store=store)

    assessment = {
        "satisfaction": {"level": 5, "level_message": "happy", "changed_topic": False},
        "pending": None,
    }
    response = client.post(
        "/sessions/s1/session",
        json={"runs": [{"user": "new", "assistant": "new"}], "interaction_assessment": assessment},
        headers=AUTH,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["runs"] == [{"user": "new", "assistant": "new"}]
    assert body["interaction_assessment"]["satisfaction"]["level"] == 5


def test_post_session_rejects_cross_user_writes():
    store = MemoryStore()
    store.save("u1", "s1", session_state={"a": 1}, runs=[])
    client, _ = _client(store=store)

    for path, payload in (
        ("/sessions/s1/session?user_id=u2", {"session_state": {"x": 1}}),
        ("/sessions/s1/session", {"user_id": "u2", "session_state": {"x": 1}}),
    ):
        assert client.post(path, json=payload, headers=AUTH).status_code == 409

    assert store.records["s1"]["user_id"] == "u1"
    assert store.records["s1"]["session_state"] == {"a": 1}


def test_post_session_requires_a_user_id_to_create():
    client, _ = _client(store=MemoryStore())

    response = client.post("/sessions/s1/session", json={"session_state": {"a": 1}}, headers=AUTH)

    assert response.status_code == 400
    assert "user_id" in response.json()["detail"]


def test_post_session_rejects_a_malformed_assessment():
    store = MemoryStore()
    store.save("u1", "s1", session_state={}, runs=[])
    client, _ = _client(store=store)

    response = client.post(
        "/sessions/s1/session", json={"interaction_assessment": {"satisfaction": {}}}, headers=AUTH
    )

    assert response.status_code == 422


def test_post_session_sanitizes_through_the_harness():
    """Writes go through Harness.sanitize, exactly like pipeline persistence."""

    def redact(data):
        if isinstance(data, dict):
            return {key: redact(value) for key, value in data.items()}
        if isinstance(data, list):
            return [redact(item) for item in data]
        if isinstance(data, str):
            return data.replace("secret", "[REDACTED]")
        return data

    store = MemoryStore()
    harness = FakeHarness(store=store)
    harness.sanitize = redact
    client, _ = _client(harness=harness)

    client.post(
        "/sessions/s1/session",
        json={"user_id": "u1", "session_state": {"note": "secret"}},
        headers=AUTH,
    )

    assert store.records["s1"]["session_state"] == {"note": "[REDACTED]"}


# ---------------------------------------------------------------- wiring
def test_semente_app_mounts_rest_by_default(monkeypatch, tmp_path):
    """REST needs no `channels` entry: SementeApp always mounts it."""
    from semente.api import SementeApp
    from semente.core import harness as harness_module

    fake = FakeHarness()
    monkeypatch.setattr(harness_module, "get_harness", lambda path: fake)
    manifest = tmp_path / "semente.yaml"
    manifest.write_text("name: groot\nchannels: [streamlit]\n", encoding="utf-8")

    app = SementeApp(manifest)
    built = app.build_app()

    paths = {route.path for route in built.routes}
    assert {"/health", "/runs", "/sessions/{session_id}/session"} <= paths
    assert app.interface_names == ["rest"]
    assert TestClient(built).get("/health").json()["name"] == "groot"


def test_openapi_documents_both_run_body_transports():
    client, _ = _client()

    operation = client.get("/openapi.json").json()["paths"]["/runs"]["post"]
    content = operation["requestBody"]["content"]

    assert set(content) == {"application/json", "multipart/form-data"}
    assert content["application/json"]["schema"]["properties"]["session_id"]
    assert content["multipart/form-data"]["schema"]["properties"]["images"]
    assert "$defs" not in json.dumps(content)  # refs are inlined


# ------------------------------------------------------- generated media map
def test_run_media_response_marks_types_and_keeps_urls():
    harness = FakeHarness()
    harness.run = lambda **kwargs: SimpleNamespace(
        content="ok",
        images=[Image(url="https://example.org/i.png", alt_text="x")],
        audio=[Audio(content=b"wav", mime_type="audio/wav")],
        videos=[Video(content=b"mp4", mime_type="video/mp4")],
        files=None,
    )
    client, _ = _client(harness=harness)

    body = client.post("/runs", json={"message": "hi"}, headers=AUTH).json()

    assert body["images"] == [
        {"type": "image", "mime_type": None, "name": None, "format": None, "url": "https://example.org/i.png", "base64": None}
    ]
    assert body["audio"][0]["type"] == "audio"
    assert body["audio"][0]["base64"] == base64.b64encode(b"wav").decode()
    assert body["videos"][0]["type"] == "video"
