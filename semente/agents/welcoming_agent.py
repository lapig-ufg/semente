from enum import Enum, auto
from typing import Any, Dict, List, Optional

from semente.backends.base import AgentSpec
from semente.backends.registry import get_backend
from semente.configs.prompts import get_agent_config
from semente.domain.base import Tutorial
from semente.schemas.user_persona import (
    is_persona_complete,
    is_persona_field_informed,
)
from semente.schemas.workflow_state import parse_tutorial_state


class OnboardingStatus(Enum):
    NOT_ACCEPTED_TERMS = auto()
    NOT_INFORMED_PERSONA = auto()
    NOT_DECIDED_TUTORIAL = auto()
    COMPLETE = auto()


def tutorial_offer_menu(tutorial: Tutorial) -> str:
    """Builds the default offer text from the Tutorial's step ids.

    The custom ``Tutorial.offer`` (set by the domain) wins; this numbered
    ids menu is the fallback the ``instructions_tutorial`` template receives
    as ``{tutorial_menu}``.
    """
    steps = " ".join(f"{i}. {step.id.strip()}" for i, step in enumerate(tutorial.steps, start=1))
    return f"a guided tutorial in {len(tutorial.steps)} steps: {steps}"


def _identifying_closing(tutorial: Optional[Tutorial]) -> str:
    """The persona stage's point-7 closing (formatted as its own key).

    With a tutorial wired, the last persona message already asks the
    tutorial question (the offer stage just records the answer next); with
    none, it simply releases the user to the system.
    """
    if tutorial is not None:
        menu = tutorial.offer.strip() if tutorial.offer and tutorial.offer.strip() else tutorial_offer_menu(tutorial)
        return (
            f"ask directly whether they want {menu} before starting. ONLY ask — "
            "do not try to record the answer: the tutorial-offer stage takes it next."
        )
    return "tell them they can start using the system right away."


def _get_onboarding_status(
    session_state: Dict[str, Any], tutorial: Optional[Tutorial] = None
) -> OnboardingStatus:
    """Decide which onboarding stage the user is currently on.

    Reads ``terms_accepted``, ``user_persona`` (a plain dict) and the
    tutorial decision (``workflow_state.tutorial_state``, hydrated from the
    database by the pipeline gate) from the session state and drives both the
    instructions and the toolset: the terms prompt/tool only while the terms
    are pending, the persona prompt/tools only while name or role are
    missing, and the tutorial-offer prompt/tool only while the tutorial is
    wired and its question is unanswered. Completeness is judged with the
    shared ``is_persona_complete`` rule, so it can never drift from the
    workflow gate.
    """
    if not session_state.get("terms_accepted", False):
        return OnboardingStatus.NOT_ACCEPTED_TERMS

    if not is_persona_complete(session_state.get("user_persona")):
        return OnboardingStatus.NOT_INFORMED_PERSONA

    tutorial_state = parse_tutorial_state(
        (session_state.get("workflow_state") or {}).get("tutorial_state")
    )
    if tutorial_state is None and tutorial is not None:
        # Terms and profile are done: the tutorial offer is still pending.
        return OnboardingStatus.NOT_DECIDED_TUTORIAL

    # Tutorial decided (in flight or done) — the pipeline routes these users
    # to the tutorial supervisor or the normal flow — or no tutorial is
    # wired at all: either way there is no welcoming instruction to give.
    return OnboardingStatus.COMPLETE


def build_welcoming_agent(tts_enabled: bool = True, tutorial: Optional[Tutorial] = None):
    """Build the staged welcoming agent via the selected engine backend.

    One stage per prompt: the terms stage (``instructions`` +
    ``accept_terms_and_conditions``), the persona stage
    (``instructions_persona`` + name/role tools) and — when the domain
    supplies a :class:`Tutorial` (``get_tutorial`` seam) — the tutorial-offer
    stage (``instructions_tutorial`` + ``set_tutorial_choice``). Only the
    current stage's tools are exposed (TTS always, when enabled). Prompts are
    loaded lazily so the language/prompts dir can be set before this is
    called; the loaded values are closed over by the callables below.
    """
    welcoming_config = get_agent_config("welcoming_agent")

    terms_instruction = welcoming_config["instructions"].strip().format(
        terms_text=welcoming_config["terms_text"].strip()
    )
    persona_instruction = welcoming_config["instructions_persona"].strip()
    persona_not_informed = welcoming_config["persona_not_informed"].strip()
    tutorial_instruction = welcoming_config["instructions_tutorial"].strip()
    identifying_closing = _identifying_closing(tutorial)
    offer_menu = (
        tutorial.offer.strip()
        if tutorial and tutorial.offer and tutorial.offer.strip()
        else (tutorial_offer_menu(tutorial) if tutorial else "")
    )

    def _get_tools(run_context) -> List:
        session_state = run_context.session_state or {}
        onboarding_status = _get_onboarding_status(session_state, tutorial)

        tools: list = []
        if tts_enabled:
            from semente.tools.tts_tools import generate_speech

            tools.append(generate_speech)

        if onboarding_status == OnboardingStatus.NOT_ACCEPTED_TERMS:
            from semente.tools.onboarding_tools import accept_terms_and_conditions

            tools.append(accept_terms_and_conditions)

        if onboarding_status == OnboardingStatus.NOT_INFORMED_PERSONA:
            from semente.tools.persona_tools import (
                update_persona_name,
                update_persona_role,
            )

            tools.extend([update_persona_name, update_persona_role])

        if onboarding_status == OnboardingStatus.NOT_DECIDED_TUTORIAL:
            from semente.tools.tutorial_tools import set_tutorial_choice

            tools.append(set_tutorial_choice)

        return tools

    def get_instructions(run_context) -> str:
        session_state = run_context.session_state or {}
        onboarding_status = _get_onboarding_status(session_state, tutorial)

        if onboarding_status == OnboardingStatus.NOT_ACCEPTED_TERMS:
            return terms_instruction

        if onboarding_status == OnboardingStatus.NOT_INFORMED_PERSONA:
            user_persona = session_state.get("user_persona") or {}

            user_name = user_persona.get("name")
            user_role = user_persona.get("role")

            if not is_persona_field_informed(user_name):
                user_name = persona_not_informed
            if not is_persona_field_informed(user_role):
                user_role = persona_not_informed

            return persona_instruction.format(
                user_name=user_name,
                user_role=user_role,
                closing_the_identification=identifying_closing,
            )

        if onboarding_status == OnboardingStatus.NOT_DECIDED_TUTORIAL:
            user_persona = session_state.get("user_persona") or {}
            user_name = user_persona.get("name")
            if not is_persona_field_informed(user_name):
                user_name = persona_not_informed

            return tutorial_instruction.format(user_name=user_name, tutorial_menu=offer_menu)

        # Onboarding complete: the workflow gate routes these users away from
        # the welcoming agent, so there is no instruction to give.
        return ""

    spec = AgentSpec(
        name=welcoming_config["name"],
        instructions=get_instructions,
        tools=_get_tools,
    )
    return get_backend().build_agent(spec)