"""Registry of property sources and the choice of the enabled ones.

Sources are registered by key with a factory (a class or a callable returning a
``PropertySource``). Which ones are enabled comes, in this order, from the
``SEMENTE_PROPERTY_SOURCES`` environment variable (comma separated keys), the
``property_sources`` list of the manifest, or the default ``["buffer"]``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

from semente.logging import log_warning
from semente.property_sources.base import PropertySource
from semente.property_sources.buffer_source import BufferSource

if TYPE_CHECKING:
    from semente.manifest import Manifest

SOURCES_ENV = "SEMENTE_PROPERTY_SOURCES"
DEFAULT_SOURCES = ["buffer"]

_factories: dict[str, Callable[[], PropertySource]] = {}
_instances: dict[str, PropertySource] = {}


def register_source(key: str, factory: Callable[[], PropertySource]) -> None:
    """Registers (or replaces) a property source.

    Args:
        key (str): Source key used in configuration and app code.
        factory (Callable): Class or callable returning a ``PropertySource`` (called once, lazily).

    Side effects:
        Drops any instance already created for the key.
    """
    _factories[key] = factory
    _instances.pop(key, None)


def get_source(key: str) -> PropertySource:
    """Returns the source registered under a key (created on first use).

    Args:
        key (str): Source key.

    Returns:
        PropertySource: The shared instance.

    Raises:
        KeyError: If no source is registered under the key.
    """
    if key in _instances:
        return _instances[key]
    if key not in _factories:
        raise KeyError(f"unknown source {key!r}")
    _instances[key] = _factories[key]()
    return _instances[key]


def _load_manifest() -> Optional["Manifest"]:
    """Loads the manifest (``SEMENTE_MANIFEST`` or ``./semente.yaml``).

    Returns:
        Manifest | None: The manifest; None when the file is absent (silent) or
        fails to load (logged as a warning), so source selection falls back to the default.
    """
    from semente.manifest import Manifest

    path = Path(os.getenv("SEMENTE_MANIFEST") or "semente.yaml")
    if not path.exists():
        return None
    try:
        return Manifest.load(path)
    except Exception as exc:
        log_warning(f"property sources: could not load manifest {str(path)!r}: {exc}")
        return None


def enabled_keys(manifest: Optional["Manifest"] = None) -> list[str]:
    """Returns the keys of the enabled sources, in priority order.

    Args:
        manifest (Manifest, optional): Manifest whose ``property_sources`` is read. When
            omitted, the manifest is loaded from ``SEMENTE_MANIFEST`` or ``./semente.yaml``;
            a missing or invalid file is tolerated.

    Returns:
        list[str]: Keys from the environment, the manifest or the default.
    """
    configured = os.getenv(SOURCES_ENV)
    if configured:
        keys = [key.strip() for key in configured.split(",") if key.strip()]
        if keys:
            return keys
    manifest = manifest if manifest is not None else _load_manifest()
    if manifest is not None and manifest.property_sources:
        return list(manifest.property_sources)
    return list(DEFAULT_SOURCES)


def enabled_sources(manifest: Optional["Manifest"] = None) -> list[PropertySource]:
    """Returns the enabled source instances, skipping (and logging) unknown keys.

    Args:
        manifest (Manifest, optional): See ``enabled_keys``.

    Returns:
        list[PropertySource]: Enabled sources in priority order.
    """
    sources = []
    for key in enabled_keys(manifest):
        try:
            sources.append(get_source(key))
        except KeyError:
            log_warning(f"property sources: unknown source {key!r} ignored")
    return sources


register_source("buffer", BufferSource)
