import re
from datetime import datetime
from semente import tool
from semente.context import Context as RunContext
from semente.guardrails import mask_text
from semente.logging import log_debug, log_error
from semente.configs.prompts import get_tool_description

from semente.database.session import SessionLocal, engine
from semente.database.models import AnalysisFeedback

# Latitude/longitude pairs are generic (not country-specific) and too long /
# too precise to trust to a generic guard's regex list — masked locally.
_COORDINATES_RE = re.compile(r"(-?\d{1,3}\.\d{4,}\s*,\s*-?\d{1,3}\.\d{4,})")


def _mask_pii(text: str) -> str:
    """Log-safe masking: the active guardrail chain + lat/long pairs.

    Country-specific spans (CPF/CNPJ/CAR in the Pasto Legal deployment) are
    covered by the guardrails the app declares — see
    ``migrate-to-pasto-legal/``.
    """
    if not text:
        return ""
    masked_text = mask_text(str(text))
    return _COORDINATES_RE.sub("[COORDINATES_HIDDEN]", masked_text)

def _get_masked_history(run_context: RunContext) -> list[dict]:
    """ Last 3 rounds (user/assistant tuples), with PII masked """
    if not run_context or not run_context.messages:
        return []

    runs: list[dict] = []
    for msg in run_context.messages:
        role = msg.get("role") if isinstance(msg, dict) else getattr(msg, "role", "")
        content = msg.get("content") if isinstance(msg, dict) else getattr(msg, "content", "")
        if role == "user":
            runs.append({"user": str(content or ""), "assistant": ""})
        elif role == "assistant" and runs:
            runs[-1]["assistant"] = str(content or "")

    history = runs[-3:]
    for run in history:
        run["user"] = _mask_pii(run["user"])
        run["assistant"] = _mask_pii(run["assistant"])
    return history

@tool(description=get_tool_description("feedback_tools", "record_analisys_feedback"))
def record_analisys_feedback(
    original_question: str, 
    desired_analysis: str,
    run_context: RunContext = None
) -> str:
    """
    Records a suggestion of a new feature or data analysis.
    Use when the user requests an analysis the assistant does not yet have tools to generate.
    """
    AnalysisFeedback.metadata.create_all(bind=engine)
    db = SessionLocal()
    log_debug("record_analisys_feedback: starting registration")
    try:
        # History of the last 3 rounds, with PII masked deterministically
        final_safe_history = _get_masked_history(run_context)
        
        new_feedback = AnalysisFeedback(
            timestamp=datetime.now().isoformat(),
            original_question=_mask_pii(original_question),
            desired_analysis=_mask_pii(desired_analysis),
            history=final_safe_history
        )
        
        db.add(new_feedback)
        db.commit()
        log_debug("record_analisys_feedback: feedback registered successfully")
        return "Feedback registered successfully in the system. Thank you very much for helping to improve it!"
    except Exception as e:
        db.rollback()
        log_error(f"record_analisys_feedback: failed to register feedback: {e}")
        return f"Failed to register feedback: {str(e)}"
    finally:
        db.close()