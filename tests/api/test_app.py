"""Tests of SementeApp: app building, interface mounting, middleware, extension."""

from types import SimpleNamespace

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from semente.api import SementeApp, SementeAPP
from semente.api.interfaces import ALWAYS_ON, AVAILABLE_INTERFACES, HTTP_INTERFACES


class FakeHarness:
    """Minimal harness stand-in: the interfaces only need ``run``/``store``."""

    name = "groot"
    store = None

    def run(self, **kwargs):
        return SimpleNamespace(content=f"echo: {kwargs['input']}")


@pytest.fixture
def manifest(tmp_path, monkeypatch):
    """Write a manifest with the given channels and return its path."""
    monkeypatch.delenv("REST_API_KEY", raising=False)
    monkeypatch.delenv("A2A_API_KEY", raising=False)

    def _write(channels: str = "streamlit") -> object:
        path = tmp_path / "semente.yaml"
        path.write_text(f"name: groot\nchannels: [{channels}]\n", encoding="utf-8")
        return path

    return _write


def _app(manifest_path, **kwargs) -> SementeApp:
    """A built SementeApp (interfaces mounted)."""
    app = SementeApp(manifest_path, harness=FakeHarness(), **kwargs)
    app.build_app()
    return app


# ------------------------------------------------------------------ catalog
def test_rest_is_the_only_always_on_interface():
    assert ALWAYS_ON == ("rest",)
    assert set(HTTP_INTERFACES) == {"rest", "whatsapp", "a2a"}
    assert set(AVAILABLE_INTERFACES) >= {"rest", "whatsapp", "a2a", "streamlit", "mcp"}


def test_alias_matches_the_class():
    assert SementeAPP is SementeApp


# ------------------------------------------------------------------ building
def test_init_does_not_build_the_app(manifest):
    app = SementeApp(manifest(), harness=FakeHarness())

    assert app.app is None
    assert app.interface_names == []


def test_build_app_returns_the_fastapi_app_and_is_idempotent(manifest):
    app = SementeApp(manifest(), harness=FakeHarness())

    built = app.build_app()

    assert isinstance(built, FastAPI)
    assert app.app is built
    assert app.build_app() is built
    assert app.app.title == "groot"
    assert app.app.version
    assert TestClient(app.build_app()).get("/openapi.json").status_code == 200


def test_build_app_accepts_an_existing_fastapi_app(manifest):
    existing = FastAPI(title="custom")
    app = SementeApp(manifest(), harness=FakeHarness())

    built = app.build_app(app=existing)

    assert built is existing
    assert existing.title == "custom"
    assert app.enabled("rest")
    # the first build wins: a later call ignores a new FastAPI instance
    assert app.build_app(app=FastAPI()) is existing


# ------------------------------------------------------------------ mounting
def test_rest_is_mounted_even_when_not_a_channel(manifest):
    app = _app(manifest("streamlit"))

    assert app.interface_names == ["rest"]
    assert app.enabled("rest")
    assert not app.enabled("whatsapp")


def test_channels_drive_the_other_interfaces(manifest, monkeypatch):
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "t")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "1")
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "v")
    app = _app(manifest("streamlit, whatsapp, a2a"))

    assert app.interface_names == ["rest", "whatsapp", "a2a"]
    paths = {route.path for route in app.app.routes}
    assert "/whatsapp/webhook" in paths
    assert "/a2a" in paths


def test_app_is_served_through_build_app(manifest):
    response = TestClient(_app(manifest()).build_app()).get("/health")

    assert response.status_code == 200
    assert response.json()["name"] == "groot"


# ---------------------------------------------------------------- middleware
def test_request_id_is_echoed_and_generated(manifest):
    client = TestClient(_app(manifest()).build_app())

    generated = client.get("/health")
    echoed = client.get("/health", headers={"X-Request-ID": "abc-123"})

    assert generated.headers["X-Request-ID"]
    assert echoed.headers["X-Request-ID"] == "abc-123"


def test_unhandled_errors_become_an_opaque_500(manifest):
    app = _app(manifest())

    @app.app.get("/boom")
    async def boom():
        raise RuntimeError("secret internals")

    response = TestClient(app.app).get("/boom")

    assert response.status_code == 500
    assert response.json()["detail"] == "Internal server error"
    assert "secret internals" not in response.text
    assert response.headers["X-Request-ID"]


def test_middleware_can_be_disabled(manifest):
    app = _app(manifest(), request_id=False)

    assert "x-request-id" not in TestClient(app.app).get("/health").headers


# ---------------------------------------------------------------- extension
def test_register_mounts_a_custom_interface(manifest):
    app = SementeApp(manifest(), harness=FakeHarness())

    class Metrics:
        name = "metrics"

        def get_router(self):
            router = APIRouter()

            @router.get("/metrics")
            async def metrics():
                return {"runs": 0}

            return router

    app.register("metrics", Metrics())  # builds the app on demand

    assert app.enabled("metrics")
    assert app["metrics"].name == "metrics"
    assert TestClient(app.build_app()).get("/metrics").json() == {"runs": 0}


def test_register_rejects_duplicates(manifest):
    app = _app(manifest())

    with pytest.raises(ValueError, match="already mounted"):
        app.register("rest", object())
