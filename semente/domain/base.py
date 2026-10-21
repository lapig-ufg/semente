"""The domain seam — the single abstraction an app implements to grow a Semente assistant.

A domain is a flat bag of Agno tools, an optional vector knowledge base, and
optional skills. No plugin registry, no interface hierarchy: the framework
assembles the workflow from this spec plus the ``semente.yaml`` manifest.

Pasto Legal's domain is: pasture-analysis tools + weather tools + property CRUD
tools + the Embrapa knowledge base + the UA-calculator skill.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class DomainSpec:
    """Everything domain-specific the framework needs to build an assistant.

    Attributes:
        name: Human-readable app name (e.g. "Pasto Legal").
        tools: Agno tool functions/objects handed to the single agent. May be a
            list or a callable ``(run_context) -> list`` for dynamic selection.
        knowledge: Optional Agno ``Knowledge`` instance (vector KB).
        skills: Optional Agno ``Skills`` instance.
        guardrails: Optional input guardrails (``semente.guardrails``
            objects/classes) run in list order over the user input at every
            stage (channels, media, pipeline, persistence).
        agent_config: Key into ``prompts/agents.yml`` selecting the agent's
            instructions/metadata. Defaults to ``single_agent``.
        instructions: Optional callable ``(run_context) -> str`` for domain-specific
            dynamic instructions. When None, a generic builder (persona + context
            blocks + ``instructions_default``) is used.
    """

    name: str
    tools: list[Any] | Callable = field(default_factory=list)
    knowledge: Any = None
    skills: Any = None
    guardrails: list = field(default_factory=list)
    agent_config: str = "single_agent"
    instructions: Optional[Callable] = None
