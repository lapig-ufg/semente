"""MyAgent — a chat-only agent, built from scratch on the provider port.

No framework: it holds an instruction and a provider, receives a message,
returns text. Stateless by design (no history, no tools, no structured
output) — those concerns belong to whoever drives the agent.
"""

from __future__ import annotations

from semente.backends.bare.providers import GeminiProvider, Provider


class MyAgent:
    """One system instruction + one provider = one chat loop."""

    def __init__(
        self,
        instructions: str,
        provider: Provider | None = None,
        model_id: str | None = None,
    ):
        self.instructions = instructions
        self.provider = provider or GeminiProvider(model_id=model_id)
        self.model_id = model_id or getattr(self.provider, "default_model", None)

    def chat(self, message: str) -> str:
        return self.provider.generate(self.instructions, message, self.model_id)