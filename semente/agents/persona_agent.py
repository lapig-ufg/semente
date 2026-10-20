from semente.context import Context

from semente.backends.base import AgentSpec
from semente.backends.registry import get_backend
from semente.configs.prompts import get_agent_config
from semente.schemas.user_persona import PersonaUpdate, UserPersona


_persona_config = get_agent_config("persona_agent")


def get_instructions(run_context: Context) -> str:
    session_state = run_context.session_state

    user_persona_dict = session_state.get("user_persona", {})
    user_persona = UserPersona.model_validate(user_persona_dict)

    negative_prompt = ""
    user_satisfaction = session_state.get("user_satisfaction")
    if user_satisfaction and user_satisfaction.level == 1:
        if user_satisfaction.approved:
            negative_prompt = _persona_config["negative_prompt_approved"].strip().format(
                new_message=user_satisfaction.new_message
            )
        else:
            negative_prompt = _persona_config["negative_prompt_rejected"].strip().format(
                new_message=user_satisfaction.new_message
            )

    instructions = _persona_config["instructions"].strip().format(
        user_persona=str(user_persona),
        satisfaction_level=user_satisfaction.level_message if user_satisfaction else 'Not informed',
        last_message=session_state.messages.last_message if hasattr(session_state, 'messages') else '',
        negative_prompt=negative_prompt,
    )

    return instructions


persona_manager_agent = get_backend().build_agent(
    AgentSpec(
        name=_persona_config["name"],
        instructions=get_instructions,
        output_schema=PersonaUpdate,
    )
)
