"""Registry: registration, lazy single instances and enabled-source precedence."""

import logging

import pytest

from semente.manifest import Manifest
from semente.property_sources import BufferSource, registry


@pytest.fixture(autouse=True)
def isolated_registry(monkeypatch, tmp_path):
    """Isolates the module registries, the env and the cwd manifest."""
    monkeypatch.setattr(registry, "_factories", dict(registry._factories))
    monkeypatch.setattr(registry, "_instances", {})
    monkeypatch.delenv("SEMENTE_PROPERTY_SOURCES", raising=False)
    monkeypatch.delenv("SEMENTE_MANIFEST", raising=False)
    monkeypatch.chdir(tmp_path)


class _Fake:
    key = "fake"

    def find_by_point(self, latitude, longitude, search_radius_m=2000):
        return []

    def find_by_id(self, identifier):
        return None


def test_buffer_is_registered_and_default():
    assert registry.enabled_keys() == ["buffer"]
    assert isinstance(registry.get_source("buffer"), BufferSource)


def test_single_instance_and_reregistration_drops_it():
    first = registry.get_source("buffer")
    assert registry.get_source("buffer") is first
    registry.register_source("buffer", _Fake)
    assert isinstance(registry.get_source("buffer"), _Fake)


def test_unknown_key_raises_keyerror():
    with pytest.raises(KeyError):
        registry.get_source("nope")


def test_env_beats_manifest_beats_default(monkeypatch):
    manifest = Manifest(name="a", property_sources=["fake"])
    assert registry.enabled_keys(manifest) == ["fake"]
    monkeypatch.setenv("SEMENTE_PROPERTY_SOURCES", " buffer , fake ,")
    assert registry.enabled_keys(manifest) == ["buffer", "fake"]


def test_empty_manifest_list_falls_back_to_default():
    assert registry.enabled_keys(Manifest(name="a")) == ["buffer"]


def test_manifest_resolved_from_env_path_then_cwd(monkeypatch, tmp_path):
    (tmp_path / "semente.yaml").write_text("name: a\nproperty_sources: [fake]\n", encoding="utf-8")
    assert registry.enabled_keys() == ["fake"]
    other = tmp_path / "other.yaml"
    other.write_text("name: b\nproperty_sources: [buffer, fake]\n", encoding="utf-8")
    monkeypatch.setenv("SEMENTE_MANIFEST", str(other))
    assert registry.enabled_keys() == ["buffer", "fake"]


def test_invalid_manifest_is_tolerated(tmp_path):
    (tmp_path / "semente.yaml").write_text("name: [unclosed\n", encoding="utf-8")
    assert registry.enabled_keys() == ["buffer"]


def test_enabled_sources_skips_unknown_with_warning(monkeypatch, caplog):
    registry.register_source("fake", _Fake)
    monkeypatch.setenv("SEMENTE_PROPERTY_SOURCES", "buffer,ghost,fake")
    with caplog.at_level(logging.WARNING, logger="semente"):
        sources = registry.enabled_sources()
    assert [s.key for s in sources] == ["buffer", "fake"]
    assert "ghost" in caplog.text


def test_separator_only_env_falls_back_to_manifest(monkeypatch):
    monkeypatch.setenv("SEMENTE_PROPERTY_SOURCES", " , ,")
    assert registry.enabled_keys(Manifest(name="a", property_sources=["fake"])) == ["fake"]
    assert registry.enabled_keys(Manifest(name="a")) == ["buffer"]


def test_failing_manifest_warns_but_absent_is_silent(tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger="semente"):
        assert registry.enabled_keys() == ["buffer"]
    assert caplog.text == ""
    (tmp_path / "semente.yaml").write_text("name: a\nproperty_sources: 3\n", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="semente"):
        assert registry.enabled_keys() == ["buffer"]
    assert "could not load manifest" in caplog.text


def test_factory_keyerror_is_not_reported_as_unknown_source():
    def broken():
        raise KeyError("inner")

    registry.register_source("broken", broken)
    with pytest.raises(KeyError) as info:
        registry.get_source("broken")
    assert "unknown source" not in str(info.value)
    with pytest.raises(KeyError, match="unknown source"):
        registry.get_source("missing")
