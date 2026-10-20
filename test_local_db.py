from semente.database.models import NegativeFeedback
from semente.database.session import SessionLocal
from semente.core.harness import Harness
from semente.core.types import Session
from semente.schemas.interaction_assessment import (
    Effectiveness,
    InteractionAssessment,
    PendingFeedback,
)


def test_e2e_negative_feedback():
    """Two-phase DPO: turn n registers (prompt, rejected) and opens a
    pending pair; turn n+1 with a positive evaluation completes the row
    with the stored new_response."""
    harness = Harness.__new__(Harness)  # skip the heavy __init__

    # ---------------- Turn n: frustration ----------------
    session = Session(user_id="test-local-db", session_id="test-local-db-2")
    # The bad exchange (the one that generated the frustration) is the
    # last entry of the history.
    session.runs = [
        {"user": "What is my CPF 123.456.789-00 and the area of the farm?",
         "assistant": "The area of the farm is 150 hectares."}
    ]
    session.interaction_assessment = InteractionAssessment(
        satisfaction=Effectiveness(level=1, level_message="frustrated user")
    )

    opened = harness._persist_feedback(session)

    assert opened is True, "frustration without topic change must open a remediation cycle"
    assert session.interaction_assessment.pending is not None

    # simulate the agent producing the better answer this turn
    session.interaction_assessment.pending.new_response = "The area of the farm is 1,500 hectares."

    db = SessionLocal()
    record_id = session.interaction_assessment.pending.record_id
    record = db.query(NegativeFeedback).filter(NegativeFeedback.id == record_id).first()
    assert record is not None
    assert record.rejected.startswith("The area of the farm")
    assert record.chosen == ""
    print("✅ Turn n: DPO record opened (prompt + rejected, chosen pending).")

    # ---------------- Turn n+1: positive evaluation ----------------
    session.interaction_assessment = InteractionAssessment(
        satisfaction=Effectiveness(level=5, level_message="correct new answer"),
        # _evaluate_satisfaction always carries the pending pair forward.
        pending=session.interaction_assessment.pending,
    )
    completed = harness._persist_feedback(session)

    assert completed is False, "turn n+1 is an evaluation turn, no new cycle"
    pending = session.interaction_assessment.pending
    assert pending is not None and pending.closed is True

    # The turn ends (run appended) and the history finalizer runs.
    session.runs.append(
        {"user": "Now it worked!", "assistant": "The area of the farm is 1,500 hectares."}
    )
    harness._finalize_pending_history(session)

    db.expire(record)
    assert record.chosen == "The area of the farm is 1,500 hectares."
    assert record.approved is True
    assert session.interaction_assessment.pending is None
    assert record.history and record.history[-1]["user"] == "Now it worked!"
    print("✅ Turn n+1: DPO pair completed with the new answer (approved=True).")
    print("📜 Chosen answer (sanitized):")
    print(record.chosen)
    print("📜 Cycle history:")
    print(record.history)

    db.close()


def test_negative_evaluation_leaves_record_open():
    harness = Harness.__new__(Harness)
    session = Session(user_id="test-local-db", session_id="test-local-db-3")
    session.runs = [{"user": "question", "assistant": "bad answer"}]
    session.interaction_assessment = InteractionAssessment(
        satisfaction=Effectiveness(level=2, level_message="still dissatisfied")
    )
    session.interaction_assessment.pending = PendingFeedback(
        record_id=0,  # placeholder: _persist_feedback only completes on positive
        new_response="better answer",
    )

    assert harness._persist_feedback(session) is False
    assert session.interaction_assessment.pending.closed is True
    print("✅ Negative evaluation: pending closed (row would be marked approved=False).")


if __name__ == "__main__":
    test_e2e_negative_feedback()
    test_negative_evaluation_leaves_record_open()