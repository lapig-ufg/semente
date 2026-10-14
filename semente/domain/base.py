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
class TutorialStep:
    """One guided step of a :class:`Tutorial` — its teaching and its rules.

    Attributes:
        id: Stable short key (e.g. ``"registration"``) — it labels the step
            in the supervisor prompt, the progress block and the offer menu.
        lesson: The teaching content of the step: what the user learns and
            the concrete action they take (e.g. "send the property's location
            in any of these ways: …").
        forward_condition: What counts as the user doing exactly what this
            step teaches — injected into the supervisor prompt so it knows
            when to forward (``forward=true``) and let the real assistant
            answer.
        complete_condition: How the step is judged concluded. A ``str`` is
            judged by the checkpoint agent from the real assistant's reply
            after the turn; a callable ``f(session_state, user_text,
            agent_reply) -> bool`` is executed by the pipeline with the live
            session state. ``False`` (or an error) never advances the step.
    """

    id: str
    lesson: str
    forward_condition: str
    complete_condition: str | Callable


@dataclass
class Tutorial:
    """The guided-tutorial specification a domain provides via ``get_tutorial``.

    The framework owns the tutorial machinery (routing, the supervisor agent,
    the completion checkpoint, step advancing, persistence of the final
    outcome); this object owns the content — the number of steps and what
    each one teaches. The generic prompts (the ``tutorial_agent`` and
    ``tutorial_check_agent`` contracts in ``agents.yml`` and the welcoming
    agent's tutorial-offer stage) are formatted with these texts.

    Attributes:
        steps: The ordered steps — any count; the tutorial is as short or
            long as this list.
        offer: Optional custom text for the welcoming agent's ask (the
            default is built from the step ids).
        closing: Optional final message after the last step concludes (a
            generic default ships in ``agents.yml``).
        abandon: Optional reply when the user leaves the tutorial early (a
            generic default ships in ``agents.yml``).
    """

    steps: list[TutorialStep]
    offer: Optional[str] = None
    closing: Optional[str] = None
    abandon: Optional[str] = None


@dataclass
class DomainSpec:
    """Everything domain-specific the framework needs to build an assistant.

    Attributes:
        name: Human-readable app name (e.g. "Pasto Legal").
        tools: Agno tool functions/objects handed to the single agent. May be a
            list or a callable ``(run_context) -> list`` for dynamic selection.
        knowledge: Optional Agno ``Knowledge`` instance (vector KB).
        skills: Optional Agno ``Skills`` instance.
        agent_config: Key into ``prompts/agents.yml`` selecting the agent's
            instructions/metadata. Defaults to ``single_agent``.
        instructions: Optional callable ``(run_context) -> str`` for domain-specific
            dynamic instructions. When None, a generic builder (persona + context
            blocks + ``instructions_default``) is used.
        get_tutorial: Optional callable ``() -> Tutorial`` describing the guided
            tutorial's steps (count, lesson, right path, completion). When None
            — or when ``features.tutorial`` is false in the manifest — the
            tutorial feature is fully off (no offer, no supervisor, no gate).
    """

    name: str
    tools: list[Any] | Callable = field(default_factory=list)
    knowledge: Any = None
    skills: Any = None
    agent_config: str = "single_agent"
    instructions: Optional[Callable] = None
    get_tutorial: Optional[Callable] = None
