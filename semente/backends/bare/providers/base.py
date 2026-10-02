"""Provider port — the contract every bare provider implements.

A provider is the thinnest possible seam over one LLM vendor: given a system
instruction and one user message, return the text reply. No tools, no
structured output, no history — the agent owns conversation shape, the
provider owns the wire.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class Provider(ABC):
    """One vendor's chat-completion surface."""

    name: str = "base"

    @abstractmethod
    def generate(self, system: str, message: str, model_id: str) -> str:
        """Send ``system`` + ``message`` to ``model_id``; return the reply text."""
        ...