"""Persona management step: conditionally updates the user persona.

Calls the persona manager agent only when:
- satisfaction level >= 2, OR
- satisfaction level < 2 AND remediation effectiveness > 3

The agent returns a PersonaUpdate with preferences (and optionally
regionality) to change. The executor applies those changes directly
to session_state['user_persona']. Name and role never change here: they are
declared identity (onboarding tools only) — deduction does not overwrite
declaration.

After applying updates (or skipping), clears user_mood from session_state.

External interface:
    manage_persona  -- StepExecutor consumed by feedback_workflow.
"""

from typing import Any, Dict

from semente.logging import log_error
from semente.backends.base import AgentInput
from semente.core.orchestrator import StepInput, StepOutput

from semente.agents.persona_agent import persona_manager_agent
from semente.schemas.user_mood import UserMood
from semente.schemas.user_persona import (
    CommunicationPreference,
    PersonaUpdate,
    UserPersona,
)


def manage_persona(step_input: StepInput, session_state: Dict[str, Any]) -> StepOutput:
    """Conditionally run the persona manager agent and apply persona updates."""
    raw_user_mood = session_state.get("user_mood", None)
    if raw_user_mood is None:
        return

    try:
        user_mood = UserMood.model_validate(raw_user_mood)
    except Exception as e:
        # A malformed user_mood would stay in session_state and break every
        # later run of this step. Drop it and move on.
        log_error(f"manage_persona: invalid user_mood discarded: {e}")
        session_state["user_mood"] = None
        return

    if (
        user_mood.satisfaction.level < 3 and
        user_mood.remediation and
        user_mood.remediation.effectiveness
        and user_mood.remediation.effectiveness.level < 4
        ):
        return

    user_msg = step_input.get_input_as_string() or ""
    try:
        turn = persona_manager_agent.run(
            AgentInput(text=user_msg, session_state={"user_mood": user_mood})
        )
        if turn and turn.structured:
            # Parse the PersonaUpdate from the agent's response
            persona_update = turn.structured
            if isinstance(persona_update, dict):
                persona_update = PersonaUpdate.model_validate(persona_update)

            # Apply updates to session_state["user_persona"]
            current_persona = session_state.get("user_persona", {})
            user_persona = (
                UserPersona.model_validate(current_persona) if current_persona else UserPersona()
            )

            # Apply scalar field updates (only if non-None)
            if persona_update.regionality is not None:
                user_persona.regionality = persona_update.regionality

            # Apply preference updates (add new, update existing)
            existing_prefs = {p.key: i for i, p in enumerate(user_persona.communication_preferences)}
            for new_pref in persona_update.communication_preferences:
                normalized_key = new_pref.key.strip().lower()
                if normalized_key in existing_prefs:
                    idx = existing_prefs[normalized_key]
                    user_persona.communication_preferences[idx] = CommunicationPreference(
                        key=normalized_key,
                        description=new_pref.description,
                    )
                else:
                    user_persona.communication_preferences.append(CommunicationPreference(
                        key=normalized_key,
                        description=new_pref.description,
                    ))
                    existing_prefs[normalized_key] = len(user_persona.communication_preferences) - 1

            session_state["user_persona"] = user_persona.model_dump()

        session_state["user_mood"] = None

    except Exception as e:
        log_error(f"manage_persona: agent failed: {e}")