"""The engine port — the contract every backend implements.

Semente owns everything except the LLM loop. A backend provides exactly three
things: model construction, agent construction, and the agent run primitive.
See MULTI_ENGINE.md for the full design.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from pydantic import BaseModel

from semente.context import Context


@dataclass
class ModelSpec:
    provider: str
    model_id: str


@dataclass
class AgentSpec:
    """Everything a backend needs to build one agent."""

    name: str
    instructions: Callable[[Context], str]
    tools: Callable[[Context], list] | list = field(default_factory=list)
    output_schema: type[BaseModel] | None = None
    model: ModelSpec | None = None
    multimodal_in: bool = False
    knowledge: Any = None
    skills: Any = None


@dataclass
class AgentInput:
    """One agent run's input.

    ``images``/``audio`` go to the model as media parts; ``files`` go to the
    model AND are injected into tools declaring a ``files`` parameter (the
    framework convention — e.g. GeoJSON attached to the run).
    """

    text: str
    images: list | None = None
    audio: list | None = None
    files: list | None = None
    session_state: dict | None = None
    user_id: str | None = None


@dataclass
class AgentTurn:
    """One agent run's output: content, media, usage, and metrics.

    ``metrics`` (the bare backend's shape, also read by the debug panel):
    token counts summed across provider rounds (``input_tokens``,
    ``output_tokens``, ``total_tokens``, ``reasoning_tokens``,
    ``cache_read_tokens``, ``tool_use_prompt_tokens``), timings
    (``duration``, ``time_to_first_token``, ``round_durations``), and
    ``tools: [{name, duration, is_error}]``. No ``cost`` — the wire carries
    no pricing.
    """

    content: str
    structured: dict | None = None
    usage: dict | None = None
    images: list | None = None
    videos: list | None = None
    audio: list | None = None
    files: list | None = None
    metrics: dict | None = None


class Agent(Protocol):
    """One LLM loop with tools, structured output, and multimodal input."""

    def run(self, input: AgentInput) -> AgentTurn: ...


class FallbackAgent:
    """Runs the primary agent; on any failure, retries once with the fallback.

    Engine-agnostic: wraps any two ``Agent`` instances. The fallback is a
    model-level safety net (rate limits, model unavailability), not a domain
    retry — any exception from the primary triggers one fallback attempt.
    """

    def __init__(self, primary: Agent, fallback: Agent):
        self.primary = primary
        self.fallback = fallback

    def run(self, input: AgentInput) -> AgentTurn:
        try:
            return self.primary.run(input)
        except Exception:
            from semente.logging import log_warning

            log_warning("primary model failed; retrying with fallback model")
            return self.fallback.run(input)


class EngineBackend(ABC):
    """A swappable agent engine (Agno, ADK, bare, …)."""

    name: str = "base"

    @abstractmethod
    def build_agent(self, spec: AgentSpec) -> Agent: ...

    def supports(self, capability: str) -> bool:
        """Capability probe (e.g. 'structured_output', 'multimodal_in')."""
        return False
