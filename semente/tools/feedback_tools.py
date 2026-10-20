import re
from datetime import datetime
from semente import tool
from semente.context import Context as RunContext
from semente.logging import log_debug, log_error
from semente.configs.prompts import get_tool_description

from semente.database.session import SessionLocal, engine
from semente.database.models import AnalysisFeedback

def _mask_pii(text: str) -> str:
    """Deterministic fallback: masks sensitive data using regex."""
    if not text:
        return ""
    
    patterns = {
        'CPF': re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b"),
        'CNPJ': re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/\d{4}-?\d{2}\b"),
        'CAR': re.compile(r"\b[A-Z]{2}-\d{7}-[A-F0-9.]+\b", re.IGNORECASE),
        'COORDINATES': re.compile(r"(-?\d{1,3}\.\d{4,}\s*,\s*-?\d{1,3}\.\d{4,})")
    }
    
    masked_text = str(text)
    for label, pattern in patterns.items():
        masked_text = pattern.sub(f"[{label}_HIDDEN]", masked_text)
        
    return masked_text

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