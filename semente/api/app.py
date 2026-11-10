"""SementeApp — the application object that replaces ``build_app``.

One object owns the app assembly: the manifest and the harness (built once,
shared by every interface) in ``__init__``; the FastAPI app and its mounted
interfaces in :meth:`SementeApp.build_app`. The REST interface is the default
and is always mounted; WhatsApp and A2A follow the manifest ``channels``.
Streamlit and MCP are interfaces too but run outside this process (see
:mod:`semente.api.interfaces`).

Usage::

    from semente.api import SementeApp

    app = SementeApp("semente.yaml").build_app()   # FastAPI, ready for uvicorn

    if __name__ == "__main__":
        import uvicorn
        uvicorn.run("main:app", host="0.0.0.0", port=3000)

``build_app()`` is idempotent (the same FastAPI instance is returned on every
call), and ``SementeApp.register(name, interface)`` mounts anything that
implements ``get_router()`` — building the app first when needed.
"""

from __future__ import annotations

import os
from importlib import metadata
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI

from semente.api.interfaces import ALWAYS_ON, HTTP_INTERFACES
from semente.api.middleware import RequestContextMiddleware
from semente.logging import log_info
from semente.manifest import Manifest


def _version() -> str:
    try:
        return metadata.version("semente-agents")
    except metadata.PackageNotFoundError:  # running from a source checkout
        return "0.0.0"


class SementeApp:
    """Assemble one Semente application and the interfaces it exposes.

    Args:
        manifest_path: Path to ``semente.yaml``. Defaults to the
            ``SEMENTE_MANIFEST`` env var or ``semente.yaml`` in the cwd.
        harness: Pre-built :class:`~semente.core.harness.Harness`; defaults to
            ``get_harness(manifest_path)`` (the cached singleton).
        request_id: Install :class:`~semente.api.middleware.RequestContextMiddleware`
            (``X-Request-ID``, access log, generic 500) on the built app.
            On by default.
    """

    def __init__(
        self,
        manifest_path: str | Path | None = None,
        *,
        harness: Any = None,
        request_id: bool = True,
    ) -> None:
        self.manifest_path = manifest_path or os.getenv("SEMENTE_MANIFEST", "semente.yaml")
        self.manifest = Manifest.load(self.manifest_path)

        if harness is None:
            from semente.core.harness import get_harness

            harness = get_harness(self.manifest_path)
        self.harness = harness

        self.request_id = request_id
        self.app: Optional[FastAPI] = None
        self.interfaces: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Assembly
    # ------------------------------------------------------------------
    def build_app(self, app: Optional[FastAPI] = None) -> FastAPI:
        """Build the FastAPI app (middleware + interfaces) and return it.

        Idempotent: the instance built by the first call is returned on every
        later call, so ``build_app()`` can be called from several places
        (uvicorn entry point, tests, an ASGI server) without doubling routers.

        Args:
            app: An existing :class:`fastapi.FastAPI` to use instead of
                creating one. Only honoured on the first call.
        """
        if self.app is not None:
            return self.app

        self.app = app or FastAPI(
            title=self.manifest.name,
            version=_version(),
            description=(
                "Semente app — the same Harness served over REST, WhatsApp and "
                "A2A. The REST API is always available."
            ),
        )
        if self.request_id:
            self.app.add_middleware(RequestContextMiddleware)

        self._mount_http_interfaces()
        return self.app

    def _mount_http_interfaces(self) -> None:
        """Mount REST (always) plus the channels the manifest enables."""
        for name, build in HTTP_INTERFACES.items():
            if name in ALWAYS_ON or name in self.manifest.channels:
                self._mount(name, build(self.harness, self.manifest))

    def _mount(self, name: str, interface: Any) -> Any:
        """Attach one interface's router to the built app."""
        assert self.app is not None, "the app must exist before mounting"
        if name in self.interfaces:
            raise ValueError(f"Interface '{name}' is already mounted.")
        self.app.include_router(interface.get_router())
        self.interfaces[name] = interface
        log_info(f"SementeApp: interface '{name}' mounted")
        return interface

    def register(self, name: str, interface: Any) -> Any:
        """Mount ``interface`` under ``name`` and return it.

        The interface only needs a ``get_router()`` returning an
        ``APIRouter`` (see :class:`semente.api.interfaces.Interface`). The app
        is built first when :meth:`build_app` has not run yet.
        """
        self.build_app()
        return self._mount(name, interface)

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------
    def enabled(self, name: str) -> bool:
        """True when ``name`` is mounted (call :meth:`build_app` first)."""
        return name in self.interfaces

    def __getitem__(self, name: str) -> Any:
        return self.interfaces[name]

    @property
    def interface_names(self) -> list[str]:
        """Names of the mounted interfaces (call :meth:`build_app` first)."""
        return list(self.interfaces)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        state = "built" if self.app is not None else "not built"
        return (
            f"SementeApp(name={self.manifest.name!r}, {state}, "
            f"interfaces={sorted(self.interfaces)})"
        )
