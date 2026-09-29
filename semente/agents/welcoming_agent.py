from enum import Enum, auto
from typing import Any, Dict, List

from semente.backends.base import AgentSpec
from semente.backends.registry import get_backend
from semente.configs.prompts import get_agent_config
from semente.schemas.user_persona import (
    is_persona_complete,
    is_persona_field_informed,
)


class OnboardingStatus(Enum):
    NOT_ACCEPTED_TERMS = auto()
    NOT_INFORMED_PERSONA = auto()
    COMPLETE = auto()


def _get_onboarding_status(session_state: Dict[str, Any]) -> OnboardingStatus:
    """Decide which onboarding stage the user is currently on.

    Reads ``terms_accepted`` and ``user_persona`` (a plain dict) from the
    session state and drives both the instructions and the toolset: the terms
    prompt/tool only while the terms are pending, the persona prompt/tools
    only while name or role are missing. Completeness is judged with the
    shared ``is_persona_complete`` rule, so it can never drift from the
    workflow gate.
    """
    if not session_state.get("terms_accepted", False):
        return OnboardingStatus.NOT_ACCEPTED_TERMS

    if not is_persona_complete(session_state.get("user_persona")):
        return OnboardingStatus.NOT_INFORMED_PERSONA

    return OnboardingStatus.COMPLETE


def build_welcoming_agent(tts_enabled: bool = True):
    """Build the staged welcoming agent via the selected engine backend.

    One stage per prompt: the terms stage (``instructions`` +
    ``accept_terms_and_conditions``) and the persona stage
    (``instructions_persona`` + name/role tools). Only the current stage's
    tools are exposed (TTS always, when enabled). Prompts are loaded lazily
    so the language/prompts dir can be set before this is called; the loaded
    values are closed over by the callables below.
    """
    welcoming_config = get_agent_config("welcoming_agent")

    terms_instruction = welcoming_config["instructions"].strip().format(
        terms_text=welcoming_config["terms_text"].strip()
    )
    persona_instruction = welcoming_config["instructions_persona"].strip()
    persona_not_informed = welcoming_config["persona_not_informed"].strip()

    def _get_tools(run_context) -> List:
        session_state = run_context.session_state or {}
        onboarding_status = _get_onboarding_status(session_state=session_state)

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

        return tools

    def get_instructions(run_context) -> str:
        session_state = run_context.session_state or {}
        onboarding_status = _get_onboarding_status(session_state=session_state)

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

            return persona_instruction.format(user_name=user_name, user_role=user_role)

        # Onboarding complete: the workflow gate routes these users away from
        # the welcoming agent, so there is no instruction to give.
        return ""

    spec = AgentSpec(
        name=welcoming_config["name"],
        instructions=get_instructions,
        tools=_get_tools,
    )
    return get_backend().build_agent(spec)