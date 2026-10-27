"""Assemble a Semente application from a manifest.

The single entry point: loads the manifest, applies the prompts dir, imports
the domain, builds the Harness (agents + pipeline), and wires the
channels. The domain is imported *inside* this function (after the prompts
dir is set) so that domain tools loading prompts at import time resolve
correctly.

No Agno ``AgentOS`` — the FastAPI app is assembled directly and the WhatsApp
and A2A routers are mounted on it.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def build_app(manifest_path: str | Path | None = None) -> Any:
    """Build the ASGI app for the app described by ``semente.yaml``.

    Args:
        manifest_path: Path to ``semente.yaml``. Defaults to the
            ``SEMENTE_MANIFEST`` env var or ``semente.yaml`` in the cwd.

    Returns:
        The FastAPI/ASGI app; serve with uvicorn.
    """
    from fastapi import FastAPI

    from semente.interfaces.whatsapp import Whatsapp
    from semente.manifest import Manifest
    from semente.core.harness import get_harness

    path = manifest_path or os.getenv("SEMENTE_MANIFEST", "semente.yaml")
    manifest = Manifest.load(path)
    agent = get_harness(path)

    app = FastAPI(title=manifest.name)
    if "whatsapp" in manifest.channels:
        whatsapp = Whatsapp(agent=agent)
        app.include_router(whatsapp.get_router())
    if "a2a" in manifest.channels:
        from semente.interfaces.a2a import A2A

        a2a = A2A(agent=agent, name=manifest.name, card=manifest.a2a)
        app.include_router(a2a.get_router())

    return app
