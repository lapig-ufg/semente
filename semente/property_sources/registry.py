"""Property source registry. Enabled keys: env ``SEMENTE_PROPERTY_SOURCES`` > manifest > ``["buffer"]``."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Optional

from semente.logging import log_warning
from semente.manifest import Manifest
from semente.property_sources.base import PropertySource
from semente.property_sources.buffer_source import BufferSource

_factories: dict[str, Callable[[], PropertySource]] = {"buffer": BufferSource}
_instances: dict[str, PropertySource] = {}


def register_source(key: str, factory: Callable[[], PropertySource]) -> None:
    """Registers (or replaces) a source factory; the instance is created on first use."""
    _factories[key] = factory
    _instances.pop(key, None)


def get_source(key: str) -> PropertySource:
    """The shared instance of a source; raises KeyError for an unregistered key."""
    if key not in _factories:
        raise KeyError(f"unknown source {key!r}")
    if key not in _instances:
        _instances[key] = _factories[key]()
    return _instances[key]


def enabled_keys(manifest: Optional[Manifest] = None) -> list[str]:
    """Enabled keys in priority order; without ``manifest`` reads ``SEMENTE_MANIFEST`` or ``./semente.yaml``."""
    keys = [k.strip() for k in os.getenv("SEMENTE_PROPERTY_SOURCES", "").split(",") if k.strip()]
    if keys:
        return keys
    if manifest is None:
        path = Path(os.getenv("SEMENTE_MANIFEST") or "semente.yaml")
        try:
            manifest = Manifest.load(path) if path.exists() else None
        except Exception as exc:
            log_warning(f"property sources: could not load manifest {str(path)!r}: {exc}")
    return list(manifest.property_sources) if manifest and manifest.property_sources else ["buffer"]


def enabled_sources(manifest: Optional[Manifest] = None) -> list[PropertySource]:
    """Instances of the enabled sources; unknown keys are skipped with a warning."""
    sources = []
    for key in enabled_keys(manifest):
        try:
            sources.append(get_source(key))
        except KeyError:
            log_warning(f"property sources: unknown source {key!r} ignored")
    return sources
