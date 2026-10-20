import re
from datetime import datetime
from semente import tool
from semente.context import Context as RunContext
from semente.logging import log_debug, log_error
from semente.configs.prompts import get_tool_description

from semente.database.session import SessionLocal, engine
from semente.database.models import AnalysisFeedback

def _mask_pii(text: str) -> str:
    """ Fallback Determinístico: Mascara dados sensíveis usando Regex """
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
        masked_text = pattern.sub(f"[{label}_OCULTO]", masked_text)
        
    return masked_text

def _get_masked_history(run_context: RunContext) -> list[dict]:
    """ Últimas 3 rodadas (tuples user/assistant), com PII mascarado """
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
    Registra uma sugestão de nova funcionalidade ou análise de dados.
    Use quando o usuário solicitar uma análise que o assistente ainda não possui ferramentas para gerar.
    """
    AnalysisFeedback.metadata.create_all(bind=engine)
    db = SessionLocal()
    log_debug("record_analisys_feedback: iniciando registro")
    try:
        # Histórico das últimas 3 rodadas, com PII mascarado deterministicamente
        final_safe_history = _get_masked_history(run_context)
        
        novo_feedback = AnalysisFeedback(
            timestamp=datetime.now().isoformat(),
            original_question=_mask_pii(original_question),
            desired_analysis=_mask_pii(desired_analysis),
            history=final_safe_history
        )
        
        db.add(novo_feedback)
        db.commit()
        log_debug("record_analisys_feedback: feedback registrado com sucesso")
        return "Feedback registrado com sucesso no sistema. Muito obrigado por ajudar a melhorar o sistema!"
    except Exception as e:
        db.rollback()
        log_error(f"record_analisys_feedback: erro ao registrar feedback: {e}")
        return f"Erro ao registrar feedback: {str(e)}"
    finally:
        db.close()