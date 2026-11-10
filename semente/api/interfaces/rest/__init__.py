"""REST interface — a plain HTTP API over the Harness.

Exposes the same agent every other channel runs:

* ``POST /runs`` — one conversation turn (JSON with base64 files, or
  multipart with real uploads).
* ``GET /sessions/{session_id}/session`` — read the persisted session.
* ``POST /sessions/{session_id}/session`` — upsert it (partial merge).
* ``GET /health`` — public liveness probe.

Auth is mandatory and Bearer-only: set ``REST_API_KEY`` and send it as
``Authorization: Bearer <key>``. Without a configured key the protected
routes answer 503 instead of running open.
"""

from semente.api.interfaces.rest.rest import REST

__all__ = ["REST"]
