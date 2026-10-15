from semente.context import Context

from semente.backends.base import AgentSpec
from semente.backends.registry import get_backend
from semente.configs.prompts import get_agent_config
from semente.schemas.interaction_assessment import Effectiveness


_remediation_config = get_agent_config("remediation_agent")
_satisfaction_config = get_agent_config("satisfaction_agent")


remediation_agent = get_backend().build_agent(
    AgentSpec(
        name=_remediation_config["name"],
        instructions=lambda run_context: _remediation_config["instructions"].strip(),
    )
)


def get_satisfaction_instructions(run_context: Context) -> str:
    session_state = run_context.session_state or {}
    user_assessment_dict = session_state.get("interaction_assessment", None)

    base_instructions = _satisfaction_config["base_instructions"].strip()

    if user_assessment_dict is None:
        scenario_text = _satisfaction_config["scenario_initial"].strip()
    else:
        scenario_text = _satisfaction_config["scenario_remediation"].strip()

    return f"{base_instructions}\n\n{scenario_text}"


satisfaction_evaluation_agent = get_backend().build_agent(
    AgentSpec(
        name=_satisfaction_config["name"],
        instructions=get_satisfaction_instructions,
        output_schema=Effectiveness,
    )
)
