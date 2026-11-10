"""Semente's HTTP API layer — one application object, many interfaces.

``SementeApp`` owns the assembly that used to live in ``semente.build``:
``__init__`` loads the manifest and builds the harness once;
``build_app()`` creates the FastAPI app and mounts the interfaces (REST is
always on; WhatsApp and A2A follow the manifest ``channels``). Streamlit and
MCP are interfaces too, but they run outside the FastAPI process and live in
:mod:`semente.api.interfaces`.
"""

from semente.api.app import SementeApp

# The user-facing spelling with the capital APP, kept as a friendly alias.
SementeAPP = SementeApp

__all__ = ["SementeApp", "SementeAPP"]
