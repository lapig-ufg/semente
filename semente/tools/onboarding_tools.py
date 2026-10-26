import datetime
from semente import tool
from semente.context import Context as RunContext
from semente.logging import log_debug, log_warning, log_error

from semente.configs.prompts import get_tool_description, get_tool_result_text
from semente.database.session import SessionLocal, engine 
from semente.database.models import UserTermsAcceptance

@tool(description=get_tool_description("onboarding_tools", "accept_terms_and_conditions"))
def accept_terms_and_conditions(run_context: RunContext) -> str:
    """
    Records the user's formal acceptance of the Terms of Use in the database.

    Only attached to the welcoming agent while ``features.terms-acceptance``
    is enabled and the user has not accepted yet.
    """
    log_debug("accept_terms_and_conditions: starting")
    session_state = run_context.session_state or {}
    user_id = run_context.user_id or session_state.get("user_id")

    if not user_id:
        log_warning("accept_terms_and_conditions: user_id missing from context")
        return get_tool_result_text(
            "onboarding_tools", "accept_terms_and_conditions", "missing_user_id"
        )

    UserTermsAcceptance.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        log_debug(f"accept_terms_and_conditions: recording acceptance for user_id={user_id}")
        record = db.query(UserTermsAcceptance).filter(UserTermsAcceptance.user_id == user_id).first()
        now = datetime.datetime.utcnow()

        if not record:
            record = UserTermsAcceptance(user_id=user_id, accepted=True, accepted_at=now)
            db.add(record)
        else:
            record.accepted = True
            record.accepted_at = now

        db.commit()

        session_state["terms_accepted"] = True
        session_state["terms_accepted_at"] = now.isoformat()

        log_debug(f"accept_terms_and_conditions: acceptance recorded for user_id={user_id}")
        return get_tool_result_text(
            "onboarding_tools", "accept_terms_and_conditions", "success"
        )
    except Exception as e:
        db.rollback()
        log_error(f"accept_terms_and_conditions: persistence error for user_id={user_id}: {e}")
        return get_tool_result_text(
            "onboarding_tools", "accept_terms_and_conditions", "error_persistence",
            error=str(e),
        )
    finally:
        db.close()
