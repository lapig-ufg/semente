"""A2A (Agent2Agent) channel — expose the app to other AI agents.

Implements the server side of the A2A protocol (https://a2a-protocol.org) on
top of the same ``Harness`` every channel uses:

* ``GET /.well-known/agent-card.json`` (and the legacy ``agent.json``) — the
  Agent Card other agents use to discover the app.
* ``POST /a2a`` — JSON-RPC 2.0 endpoint. ``message/send`` runs one full
  harness turn and answers with an agent ``Message``.

Scope (declared in the card): text in / text out, no streaming, no push
notifications, no task store — every call is answered synchronously with a
``Message``, so ``tasks/get`` and ``tasks/cancel`` report "task not found" and
``message/stream`` is "unsupported". The conversation continues through the
``contextId`` returned by the server.

Auth is optional: set ``A2A_API_KEY`` and clients must send it as
``Authorization: Bearer <key>`` (or ``X-API-Key``); the card then advertises
the scheme. Set ``A2A_PUBLIC_URL`` when the app sits behind a proxy so the
card carries the externally reachable URL.
"""

from semente.interfaces.a2a.a2a import A2A

__all__ = ["A2A"]
