"""SupervisedRun-flow tools — record the user's choice about the supervised_run offer.

Per the flow design, the database only ever receives the FINAL outcome
(declining at the offer, leaving the supervised_run early, or completing its last
step) — the in-flight step lives exclusively in the session state, so
resetting the session just re-offers the supervised_run to a user who has not
reached a final outcome yet.
"""

import datetime
from typing import Optional

from semente import tool
from semente.context import Context as RunContext
from semente.logging import log_debug, log_error, log_warning

from semente.configs.prompts import get_tool_description, get_tool_result_text
from semente.database.models import UserSupervisedRunProgress
from semente.database.session import SessionLocal, engine
from semente.schemas.workflow_state import SUPERVISED_RUN_COMPLETED


# =====================================================================
# HELPERS INTERNOS (não são tools — o agente não enxerga)
# =====================================================================


def _persist_supervised_run_completion(user_id: str) -> bool:
    """Writes the final supervised_run row for the user (creates the table if needed)."""
    UserSupervisedRunProgress.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        now = datetime.datetime.utcnow()
        record = db.query(UserSupervisedRunProgress).filter(UserSupervisedRunProgress.user_id == user_id).first()
        if record is None:
            record = UserSupervisedRunProgress(user_id=user_id, completed=True, completed_at=now)
            db.add(record)
        else:
            record.completed = True
            record.completed_at = now
        db.commit()
        return True
    except Exception as e:
        db.rollback()
        log_error(f"_persist_supervised_run_completion: falha para user_id={user_id}: {e}")
        return False
    finally:
        db.close()


def set_session_supervised_run_state(
    session_state: dict, supervised_run_state: int | str, intro_sent: bool = False
) -> None:
    """Updates the supervised_run position inside ``session_state["workflow_state"]``.

    ``supervised_run_state`` is the 0-based step index (the step count comes from
    the domain's ``SupervisedRun`` object) — or the ``COMPLETED`` terminal
    sentinel. ``intro_sent`` tells the pipeline whether the current step's
    lesson has already been delivered — the supervisor relies on it to
    deliver each step's intro before grading the user's path.
    """
    workflow_state = session_state.setdefault("workflow_state", {})
    workflow_state["supervised_run_state"] = str(supervised_run_state)
    workflow_state["supervised_run_intro_sent"] = intro_sent


def mark_supervised_run_completed(session_state: dict, user_id: Optional[str]) -> None:
    """Closes the supervised_run for good: final state in the session + one row in the database."""
    set_session_supervised_run_state(session_state, SUPERVISED_RUN_COMPLETED, intro_sent=True)
    if not user_id:
        log_warning(
            "mark_supervised_run_completed: user_id ausente, finalização gravada apenas na sessão"
        )
        return

    if not _persist_supervised_run_completion(user_id):
        log_warning(
            f"mark_supervised_run_completed: falha de persistência para user_id={user_id}; "
            "finalização gravada apenas na sessão"
        )


# =====================================================================
# TOOLS
# =====================================================================


@tool(description=get_tool_description("supervised_run_tools", "set_supervised_run_choice"))
def set_supervised_run_choice(wants_supervised_run: bool, run_context: RunContext) -> str:
    """
    Registers whether the user accepted the guided supervised_run.

    Use it exactly once, at the moment the user clearly answers the supervised_run
    offer. When the answer is ambiguous, do not call the tool — ask again in
    other words.
    """
    log_debug(f"set_supervised_run_choice: wants_supervised_run={wants_supervised_run}")
    try:
        session_state = run_context.session_state or {}
        user_id = run_context.user_id or session_state.get("user_id")

        if wants_supervised_run:
            # Accepting only starts the flow: the in-flight step lives in the
            # session state, and the database stays untouched until the final
            # outcome.
            set_session_supervised_run_state(session_state, 0, intro_sent=False)
            run_context.session_state = session_state
            log_debug("set_supervised_run_choice: supervised_run aceito, primeiro passo iniciado")
            return get_tool_result_text(
                "supervised_run_tools", "set_supervised_run_choice", "accepted"
            )

        # Declining is a final outcome: persist it so the offer never returns,
        # and mirror it on the session state for this run's routing.
        mark_supervised_run_completed(session_state, user_id)
        run_context.session_state = session_state
        log_debug("set_supervised_run_choice: supervised_run recusado")
        return get_tool_result_text("supervised_run_tools", "set_supervised_run_choice", "declined")
    except Exception as e:
        log_error(f"set_supervised_run_choice: {e}")
        return f"Erro ao registrar a escolha sobre o supervised_run: {str(e)}"