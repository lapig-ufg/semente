"""PII guardrail step: redacts personal data from the consolidated input text.

Reuses the text assembled by the previous input-processing step, replaces any
personal datum with a marker (`[CPF_OCULTO]`) and lets the message continue,
instead of rejecting it. The user keeps the requests they made in the same
message, and the datum never reaches the agent.

Typed text is already redacted at the entry doors (MessageContent.__post_init__
in whatsapp/helpers.py, streamlit_webapp.py). This step covers the text that
only becomes text inside the workflow: the audio transcription and the image
description, produced by input_step — but those are redacted THERE, not here:
each step's output is persisted in the run's step results, so redacting only
in this step would leave a raw copy in the database.

External interface:
    _guardrail_pii_executor  -- StepExecutor consumed by base_workflow.
"""
from semente.logging import log_info
from semente.core.orchestrator import Step
from semente.core.orchestrator import StepInput, StepOutput

from semente.guardrails.pii_gate import redigir_pii


def _guardrail_pii_executor(step_input: StepInput) -> StepOutput:
    """Redacts personal data from the text consolidated by the previous step.

    Reads `previous_step_content` and not `get_input_as_string()` alone: the
    latter returns the ORIGINAL workflow input, which would leave the audio
    transcription and the image description out of the scan.
    """
    conteudo = step_input.previous_step_content or step_input.get_input_as_string() or ""
    text = conteudo if isinstance(conteudo, str) else str(conteudo)

    limpo, tipos = redigir_pii(text)

    if tipos:
        # Only the types, never the values.
        log_info(f"guardrail PII: dados removidos ({', '.join(tipos)})")

    return StepOutput(content=limpo)


guardrails_step = Step(
    name="Guardrail PII",
    executor=_guardrail_pii_executor,
)