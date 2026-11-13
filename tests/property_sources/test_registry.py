import logging

import pytest

from semente.manifest import Manifest
from semente.property_sources import BufferSource, registry


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
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


def test_default_single_instance_and_reregistration():
    assert registry.enabled_keys() == ["buffer"]
    first = registry.get_source("buffer")
    assert isinstance(first, BufferSource) and registry.get_source("buffer") is first
    registry.register_source("buffer", _Fake)
    assert isinstance(registry.get_source("buffer"), _Fake)


def test_keyerrors():
    with pytest.raises(KeyError, match="unknown source"):
        registry.get_source("missing")

    def broken():
        raise KeyError("inner")

    registry.register_source("broken", broken)
    with pytest.raises(KeyError) as info:
        registry.get_source("broken")
    assert "unknown source" not in str(info.value)


def test_precedence_env_manifest_default(monkeypatch):
    manifest = Manifest(name="a", property_sources=["fake"])
    assert registry.enabled_keys(manifest) == ["fake"]
    monkeypatch.setenv("SEMENTE_PROPERTY_SOURCES", " buffer , fake ,")
    assert registry.enabled_keys(manifest) == ["buffer", "fake"]
    monkeypatch.setenv("SEMENTE_PROPERTY_SOURCES", " , ,")
    assert registry.enabled_keys(manifest) == ["fake"]
    assert registry.enabled_keys(Manifest(name="a")) == ["buffer"]


def test_manifest_path_resolution_and_broken_manifest(monkeypatch, tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger="semente"):
        assert registry.enabled_keys() == ["buffer"]
    assert caplog.text == ""
    (tmp_path / "semente.yaml").write_text("name: a\nproperty_sources: [fake]\n", encoding="utf-8")
    assert registry.enabled_keys() == ["fake"]
    other = tmp_path / "other.yaml"
    other.write_text("name: a\nproperty_sources: 3\n", encoding="utf-8")
    monkeypatch.setenv("SEMENTE_MANIFEST", str(other))
    with caplog.at_level(logging.WARNING, logger="semente"):
        assert registry.enabled_keys() == ["buffer"]
    assert "could not load manifest" in caplog.text


def test_enabled_sources_skips_unknown_with_warning(monkeypatch, caplog):
    registry.register_source("fake", _Fake)
    monkeypatch.setenv("SEMENTE_PROPERTY_SOURCES", "buffer,ghost,fake")
    with caplog.at_level(logging.WARNING, logger="semente"):
        sources = registry.enabled_sources()
    assert [s.key for s in sources] == ["buffer", "fake"]
    assert "ghost" in caplog.text


def test_enabled_sources_does_not_mask_a_factory_keyerror(monkeypatch):
    def broken():
        raise KeyError("inner")

    registry.register_source("broken", broken)
    monkeypatch.setenv("SEMENTE_PROPERTY_SOURCES", "broken")
    with pytest.raises(KeyError, match="inner"):
        registry.enabled_sources()
