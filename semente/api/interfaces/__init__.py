"""The interface catalogue — everything an app can be exposed through.

Two kinds share one folder:

* **HTTP interfaces** (``rest``, ``whatsapp``, ``a2a``) are FastAPI router
  factories mounted on the app by :class:`semente.api.app.SementeApp`. REST is
  always mounted; the other two follow the manifest ``channels`` list.
* **CLI interfaces** (``streamlit``, ``mcp``) run in their own process and are
  never mounted — ``semente launch streamlit`` and ``semente mcp`` start them.

Adding one: implement ``name`` + ``get_router()`` (see :class:`Interface`),
register a factory in :data:`HTTP_INTERFACES`, or mount an ad-hoc interface
with ``SementeApp.register(name, interface)``.
"""

from __future__ import annotations

from typing import Any, Callable, Protocol, runtime_checkable

from fastapi import APIRouter

from semente.manifest import Manifest

#: Interfaces mounted on the FastAPI app, keyed by the manifest channel name.
HTTP_INTERFACES: dict[str, Callable[[Any, Manifest], Any]] = {}

#: Mounted regardless of ``manifest.channels`` — the default interface.
ALWAYS_ON: tuple[str, ...] = ("rest",)

#: Interfaces launched outside the FastAPI app (one line each, for docs/CLI).
CLI_INTERFACES: dict[str, str] = {
    "streamlit": "Local web chat (semente launch streamlit)",
    "mcp": "stdio MCP server wrapping a remote A2A agent (semente mcp)",
}


@runtime_checkable
class Interface(Protocol):
    """What :meth:`SementeApp.register` needs from an interface."""

    name: str

    def get_router(self) -> APIRouter: ...


def _build_rest(harness: Any, manifest: Manifest) -> Any:
    from semente.api.interfaces.rest import REST

    return REST(agent=harness, name=manifest.name)


def _build_whatsapp(harness: Any, manifest: Manifest) -> Any:
    from semente.api.interfaces.whatsapp import Whatsapp

    return Whatsapp(agent=harness)


def _build_a2a(harness: Any, manifest: Manifest) -> Any:
    from semente.api.interfaces.a2a import A2A

    return A2A(agent=harness, name=manifest.name, card=manifest.a2a)


# Factories are lazy: the interface modules build engine objects at import
# time, which must only happen after the harness applied the prompts dir.
HTTP_INTERFACES.update(
    {
        "rest": _build_rest,
        "whatsapp": _build_whatsapp,
        "a2a": _build_a2a,
    }
)

#: Every interface name the app knows about (mounted or CLI-launched).
AVAILABLE_INTERFACES: tuple[str, ...] = tuple(HTTP_INTERFACES) + tuple(CLI_INTERFACES)

__all__ = [
    "ALWAYS_ON",
    "AVAILABLE_INTERFACES",
    "CLI_INTERFACES",
    "HTTP_INTERFACES",
    "Interface",
]
