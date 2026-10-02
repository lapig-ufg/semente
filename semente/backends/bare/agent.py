"""MyAgent — a chat-only agent, built from scratch on the provider port.

No framework: it holds an instruction and a provider, receives a message,
returns text. Stateless by design (no history, no tools, no structured
output) — those concerns belong to whoever drives the agent.

``from_spec``/``run`` make it speak the framework's ``Agent`` protocol, so
``BareBackend`` can route pure-chat specs here while richer specs fall back
to the litellm tool loop (``tool_loop.py``).
"""

from __future__ import annotations

from typing import Callable

from semente.backends.base import AgentInput, AgentSpec, AgentTurn
from semente.backends.bare.providers import GeminiProvider, Provider
from semente.backends.toolkit import StateContext


class MyAgent:
    """One system instruction + one provider = one chat loop."""

    def __init__(
        self,
        instructions: str | Callable[..., str],
        provider: Provider | None = None,
        model_id: str | None = None,
    ):
        self.instructions = instructions
        self.provider = provider or GeminiProvider(model_id=model_id)
        self.model_id = model_id or getattr(self.provider, "default_model", None)

    def _system(self, ctx: StateContext) -> str:
        if callable(self.instructions):
            try:
                return self.instructions(ctx)
            except TypeError:
                return self.instructions()
        return self.instructions

    def chat(self, message: str, session_state: dict | None = None, user_id: str | None = None) -> str:
        ctx = StateContext(session_state or {}, user_id)
        return self.provider.generate(self._system(ctx), message, self.model_id)

    @classmethod
    def from_spec(cls, spec: AgentSpec) -> MyAgent:
        """Build from the engine-neutral ``AgentSpec``."""
        return cls(
            instructions=spec.instructions,
            model_id=spec.model.model_id if spec.model else None,
        )

    def run(self, input: AgentInput) -> AgentTurn:
        """Framework run primitive: one message in, one text turn out."""
        return AgentTurn(
            content=self.chat(
                input.text or "",
                session_state=input.session_state,
                user_id=input.user_id,
            )
        )