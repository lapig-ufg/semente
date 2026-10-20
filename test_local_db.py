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
        {"user": "Qual o meu CPF 123.456.789-00 e a área da fazenda?",
         "assistant": "A área da fazenda é de 150 hectares."}
    ]
    session.interaction_assessment = InteractionAssessment(
        satisfaction=Effectiveness(level=1, level_message="usuário frustrado")
    )

    opened = harness._persist_feedback(session)

    assert opened is True, "frustration without topic change must open a remediation cycle"
    assert session.interaction_assessment.pending is not None

    # simulate the agent producing the better answer this turn
    session.interaction_assessment.pending.new_response = "A área da fazenda é de 1.500 hectares."

    db = SessionLocal()
    record_id = session.interaction_assessment.pending.record_id
    record = db.query(NegativeFeedback).filter(NegativeFeedback.id == record_id).first()
    assert record is not None
    assert record.payload["rejected"].startswith("A área da fazenda")
    assert record.payload["chosen"] == ""
    print("✅ Turn n: registro DPO aberto (prompt + rejected, chosen pendente).")

    # ---------------- Turn n+1: positive evaluation ----------------
    session.interaction_assessment = InteractionAssessment(
        satisfaction=Effectiveness(level=5, level_message="nova resposta correta"),
        # _evaluate_satisfaction always carries the pending pair forward.
        pending=session.interaction_assessment.pending,
    )
    completed = harness._persist_feedback(session)

    assert completed is False, "turn n+1 is an evaluation turn, no new cycle"
    assert session.interaction_assessment.pending is None

    db.expire(record)
    assert record.payload["chosen"] == "A área da fazenda é de 1.500 hectares."
    assert record.payload["approved"] is True
    print("✅ Turn n+1: par DPO completado com a nova resposta (approved=True).")
    print("📝 Payload final (Sanitizado):")
    print(record.payload)

    db.close()


def test_negative_evaluation_leaves_record_open():
    harness = Harness.__new__(Harness)
    session = Session(user_id="test-local-db", session_id="test-local-db-3")
    session.runs = [{"user": "pergunta", "assistant": "resposta ruim"}]
    session.interaction_assessment = InteractionAssessment(
        satisfaction=Effectiveness(level=2, level_message="ainda insatisfeito")
    )
    session.interaction_assessment.pending = PendingFeedback(
        record_id=0,  # placeholder: _persist_feedback only completes on positive
        new_response="resposta melhor",
    )

    assert harness._persist_feedback(session) is False
    assert session.interaction_assessment.pending is None
    print("✅ Avaliação negativa: pendência descartada (linha seria marcada approved=False).")


if __name__ == "__main__":
    test_e2e_negative_feedback()
    test_negative_evaluation_leaves_record_open()