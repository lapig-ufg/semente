"""Assemble a Semente application from a manifest.

The single entry point: loads the manifest, applies the prompts dir, imports
the domain, builds the Semente (agents + pipeline), and wires the
channels. The domain is imported *inside* this function (after the prompts
dir is set) so that domain tools loading prompts at import time resolve
correctly.

No Agno ``AgentOS`` — the FastAPI app is assembled directly and the WhatsApp
router is mounted on it.
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
    from semente.core.semente_agent import get_agent

    path = manifest_path or os.getenv("SEMENTE_MANIFEST", "semente.yaml")
    manifest = Manifest.load(path)
    agent = get_agent(path)

    app = FastAPI(title=manifest.name)
    if "whatsapp" in manifest.channels:
        whatsapp = Whatsapp(agent=agent)
        app.include_router(whatsapp.get_router())

    return app
