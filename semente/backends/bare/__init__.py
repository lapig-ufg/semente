"""Bare backend — no agent framework: our own agents over the provider port.

Semente already owns orchestration, state, sessions, media (A-M), hooks (A-H)
and knowledge (A-K). What an engine still has to do is the LLM loop. This
backend owns that loop with **two** implementations:

- ``MyAgent`` (``agent.py``): chat-only — instructions + message in, text
  out. No framework, no litellm; it talks to the vendor through the
  provider port (``providers/``), currently Gemini over google-genai.
- ``BareAgentAdapter`` (``tool_loop.py``): the full-capability path over
  litellm — tool calling, structured output, multimodal input, knowledge.

``BareBackend.build_agent`` routes each spec to the simplest agent that can
serve it: pure chat specs go to ``MyAgent``; anything richer (tools, schemas,
media, KB, non-Google providers) falls back to the tool loop.
"""

from __future__ import annotations

from semente.backends.bare.agent import MyAgent
from semente.backends.bare.tool_loop import BareAgentAdapter
from semente.backends.base import Agent, AgentInput, AgentSpec, AgentTurn, EngineBackend
from semente.configs.config import config


def _is_pure_chat(spec: AgentSpec) -> bool:
    """True when MyAgent can serve this spec: no tools, no structured output,
    no multimodal input, no knowledge — and a Gemini (or unset) model."""
    if spec.tools or spec.output_schema or spec.multimodal_in or spec.knowledge:
        return False
    if spec.model is None:
        return config.PRIMARY_MODEL_PROVIDER == "google"
    return spec.model.provider == "google"


class BareBackend(EngineBackend):
    name = "bare"

    def build_agent(self, spec: AgentSpec) -> Agent:
        if _is_pure_chat(spec):
            return MyAgent.from_spec(spec)
        return BareAgentAdapter(spec)

    def supports(self, capability: str) -> bool:
        return capability in {"structured_output", "multimodal_in", "media_out"}