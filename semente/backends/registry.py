"""Engine backend registry — selects the backend by name.

Resolution order: an explicit argument (the main agent passes the manifest's
engine) > the pinned engine (``set_engine``, called once by ``get_agent``
after loading the manifest so sub-agents built at module import time honor
it) > the ``SEMENTE_ENGINE`` env var > ``agno``.
"""

from __future__ import annotations

import os

from semente.backends.base import EngineBackend

_pinned_engine: str | None = None


def set_engine(engine: str | None) -> None:
    """Pin the app's engine (from the manifest ``engine`` field).

    Called by ``get_agent`` before any sub-agent module is imported, so
    every ``get_backend()`` call in the app resolves to the same engine.
    """
    global _pinned_engine
    _pinned_engine = engine or None


def get_backend(engine: str | None = None) -> EngineBackend:
    name = engine or _pinned_engine or os.getenv("SEMENTE_ENGINE", "agno")

    if name == "agno":
        from semente.backends.agno import AgnoBackend

        return AgnoBackend()

    if name == "adk":
        from semente.backends.adk import AdkBackend

        return AdkBackend()

    if name == "bare":
        from semente.backends.bare import BareBackend

        return BareBackend()

    raise ValueError(f"Unknown engine: {name!r} (available: agno, adk, bare)")