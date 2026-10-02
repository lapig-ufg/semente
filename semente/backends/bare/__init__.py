"""Bare backend — no agent framework: our own agents over the provider port.

Semente already owns orchestration, state, sessions, media (A-M), hooks (A-H)
and knowledge (A-K). What an engine still has to do is the LLM loop. This
backend owns that loop with one implementation:

- ``MyAgent`` (``agent.py``): instructions, message, and tools in; text and
  media out. No framework, no litellm; it drives the tool loop over the
  provider port (``providers/``), currently Gemini over google-genai. Tool
  execution itself is engine-neutral (``backends/toolkit.py``).

``BareBackend.build_agent`` routes **every** spec to ``MyAgent``. Known gaps
(planned on ``MyAgent``, see DECISIONS.md): structured output (``AgentTurn.
structured`` stays None — callers degrade gracefully), multimodal input,
knowledge-base search, and non-Google providers (ollama/passthrough).

Event system (``events.py``): ``agent.subscribe(AgentEvents.X, handler)``
observes or customizes runs — ``AGENT_START``/``AGENT_END`` at the run
boundaries, ``TOOL_EXECUTION_START``/``TOOL_EXECUTION_END`` around each tool
execution; mutating the start event's ``tool_name``/``args`` redirects
execution.

Skills: ``MyAgent(skills=...)`` takes a ``Skills`` object or a callable
``(run_context) -> Skills | None`` resolved against the run's state — the
same pattern as instructions and tools. Loaded via the engine-neutral
``semente.skills`` module, injected into every run as the
``<skills_system>`` instructions + access tools.
"""

from __future__ import annotations

from semente.backends.base import Agent, AgentSpec, EngineBackend
from semente.backends.bare.agent import MyAgent
from semente.backends.bare.events import (
    AgentEndEvent,
    AgentEvents,
    AgentMessage,
    AgentStartEvent,
    EventBus,
    ToolExecutionEndEvent,
    ToolExecutionStartEvent,
)
from semente.backends.bare.metrics import AgentMetrics


class BareBackend(EngineBackend):
    name = "bare"

    def build_agent(self, spec: AgentSpec) -> Agent:
        return MyAgent.from_spec(spec)

    def supports(self, capability: str) -> bool:
        return capability in {"media_out"}