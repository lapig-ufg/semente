"""Provider port — the contract every bare provider implements.

A provider is the thinnest possible seam over one LLM vendor's wire: it does
one typed round-trip (declarations in, text + tool calls out) and builds
the provider-native turns the model expects to see echoed back. The agent owns
the loop — parsing calls, executing tools (engine-neutral, via
``backends/toolkit.py``), feeding results — so adding a vendor never
duplicates loop logic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from semente.tools.types import Tool


@dataclass
class ToolCall:
    """One function call the model wants executed (provider-neutral)."""

    id: str | None
    name: str
    args: dict


@dataclass
class GenerateResult:
    """One provider round-trip.

    ``turn`` is the provider-native model turn; the agent echoes it back
    verbatim (Gemini 3 thought signatures live there) before tool results.
    ``usage`` is the provider-neutral token dict for this round (keys:
    ``input_tokens``, ``output_tokens``, ``total_tokens``,
    ``reasoning_tokens``, ``cache_read_tokens``, ``tool_use_prompt_tokens``;
    absent counts dropped) — the vendor's usage object never leaves the
    provider.
    """

    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    turn: Any = None
    usage: dict | None = None


class Provider(ABC):
    """One vendor's generate-content surface."""

    name: str = "base"

    @abstractmethod
    def generate(
        self,
        system: str,
        message: str | None = None,
        model_id: str | None = None,
        tools: list[Tool] | None = None,
        history: list | None = None,
        media: list[dict] | None = None,
    ) -> GenerateResult:
        """One round-trip: declarations in, text + tool calls out.

        ``message`` is the user's text (None when history already carries it);
        ``history`` is the accumulated provider-native turns of this run
        (user turn, model turn, tool results turn, …) — opaque to the agent,
        meaningful only to the provider. ``media`` is the run's multimodal
        input as provider-neutral parts (``kind``/``mime_type``/``data`` or
        ``url``); a provider that cannot take media ignores it.
        """
        ...

    def user_turn(self, message: str, media: list[dict] | None = None) -> Any:
        """Provider-native turn for the user's message (+ optional media)."""
        return {"role": "user", "content": message}

    def tool_results_turn(self, outputs: list[tuple[ToolCall, str]]) -> list:
        """Provider-native turn(s) conveying executed tool outputs.

        ``outputs`` pairs each ``ToolCall`` with its text output. The agent
        echoes the model's own turn separately; this builds only what the
        model expects to receive back. Base raises so a vendor can't
        silently drop tool results.
        """
        raise NotImplementedError(f"{type(self).__name__} does not support tool calling")