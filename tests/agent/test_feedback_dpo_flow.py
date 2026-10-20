"""Runtime tests of the two-phase DPO feedback flow in ``Harness``.

The previous implementation reconstructed the (prompt, rejected, chosen)
pair from ``recent_agent_runs`` during the remediation turn, which always
raced the agent run — the pair collapsed into a SFT-shaped row with an
empty ``rejected``. The new design registers the rejected half at the
frustration turn and completes the stored row one turn later from
``assessment.pending``.
"""

from dataclasses import dataclass, field
from typing import Any

import pytest

from semente.core.harness import Harness, _REMEDIATION_INSTRUCTION
from semente.core.types import StepOutput
from semente.database.models import NegativeFeedback, PositiveFeedback
from semente.database.session import SessionLocal, engine
from semente.manifest import Manifest
from semente.schemas.interaction_assessment import (
    Effectiveness,
    InteractionAssessment,
)
from semente.schemas.user_persona import PersonaUpdate


# ---------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------

@dataclass
class _FakeTurn:
    content: str = ""
    structured: Any = None
    tools: list = field(default_factory=list)
    messages: list = field(default_factory=list)


class _FakeSatisfaction:
    """Satisfaction agent whose evaluation is mutated per test."""

    def __init__(self):
        self.level = 3
        self.changed_topic = False

    def run(self, agent_input):
        return _FakeTurn(
            structured=Effectiveness(
                level=self.level,
                level_message=f"level {self.level}",
                changed_topic=self.changed_topic,
            )
        )


class _FakeRemediation:
    """Remediation agent echoing the classic three-part output."""

    def __init__(self):
        self.apology = ""
        self.evaluation = ""
        self.fail = False

    def run(self, agent_input):
        if self.fail:
            raise RuntimeError("remediation down")
        return _FakeTurn(
            content=f"{self.apology}\n[PAUSE]\n{agent_input.text}\n[PAUSE]\n{self.evaluation}"
        )


class _FakePersona:
    """Persona manager applying nothing."""

    def run(self, agent_input):
        return _FakeTurn(structured=PersonaUpdate())


def _harness() -> Harness:
    return Harness(agent=object(), welcoming_agent=object(), manifest=Manifest(name="test-app"))


# ---------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------

@pytest.fixture
def db():
    NegativeFeedback.metadata.create_all(bind=engine)
    PositiveFeedback.metadata.create_all(bind=engine)
    sessao = SessionLocal()
    _limpar(sessao)
    yield sessao
    _limpar(sessao)
    sessao.close()


def _limpar(sessao) -> None:
    sessao.query(NegativeFeedback).delete()
    sessao.query(PositiveFeedback).delete()
    sessao.commit()


@pytest.fixture
def feedback_agents(monkeypatch):
    """Patch the (lazily imported) feedback/persona agents with controllable
    fakes. Mutate the returned fakes to change each test's evaluation."""
    import semente.agents.feedback_agent as feedback_module
    import semente.agents.persona_agent as persona_module

    fake = {
        "satisfaction": _FakeSatisfaction(),
        "remediation": _FakeRemediation(),
        "persona": _FakePersona(),
    }
    monkeypatch.setattr(feedback_module, "satisfaction_evaluation_agent", fake["satisfaction"])
    monkeypatch.setattr(feedback_module, "remediation_agent", fake["remediation"])
    monkeypatch.setattr(persona_module, "persona_manager_agent", fake["persona"])
    return fake


# ---------------------------------------------------------------------
# Tests — turn n: frustration detection
# ---------------------------------------------------------------------

def test_frustration_registers_rejected_and_opens_pending(db, feedback_agents):
    """Turn n: the bad exchange is registered immediately (chosen empty)
    and the pending pair is opened."""
    feedback_agents["satisfaction"].level = 1
    feedback_agents["satisfaction"].changed_topic = False
    harness = _harness()

    session = _session_with_bad_answer()
    needs_remediation = harness._process_feedback(
        session, "Essa resposta está errada!", session.session_state
    )

    assert needs_remediation is True
    pending = session.interaction_assessment.pending
    assert pending is not None
    assert pending.record_id
    assert pending.new_response == ""
    # The cycle's history starts at the run _persist_session will append.
    assert pending.cycle_start == len(session.runs)

    record = db.query(NegativeFeedback).filter(
        NegativeFeedback.id == pending.record_id
    ).first()
    assert record is not None
    assert record.prompt == "Qual a área da fazenda?"
    assert record.rejected == "A área é 150 hectares."
    assert record.chosen == ""  # completed only on turn n+1
    assert record.approved is None


def test_topic_change_registers_but_skips_remediation(db, feedback_agents):
    """A frustration about a new topic still registers, but opens no
    remediation cycle (no injected instruction / apology)."""
    feedback_agents["satisfaction"].level = 1
    feedback_agents["satisfaction"].changed_topic = True
    harness = _harness()

    session = _session_with_bad_answer()
    needs_remediation = harness._process_feedback(
        session, "Quanto é 2 + 2?", session.session_state
    )

    assert needs_remediation is False
    # The rejected half is still registered — pending for evaluation next turn.
    assert session.interaction_assessment.pending is not None
    assert session.interaction_assessment.pending.closed is False


def test_remediation_instruction_injection():
    harness = _harness()
    state = {}

    clean = harness._build_agent_input(_session_with_bad_answer(), "oi", state, remediate=False)
    assert "<feedback_instruction>" not in clean

    remediated = harness._build_agent_input(
        _session_with_bad_answer(), "oi", state, remediate=True
    )
    assert _REMEDIATION_INSTRUCTION in remediated
    assert "<input>\noi\n</input>" in remediated


def test_generate_apology_orders_apology_first(feedback_agents):
    """Final message: FIRST apology + evaluation request, THEN the new answer."""
    feedback_agents["remediation"].apology = "Desculpe! A resposta anterior estava errada."
    feedback_agents["remediation"].evaluation = "Essa nova resposta ficou melhor?"
    harness = _harness()
    routed = StepOutput(content="A resposta corrigida.")

    final = harness._generate_apology(routed)

    assert final.content.startswith("Desculpe! A resposta anterior estava errada.")
    assert "Essa nova resposta ficou melhor?" in final.content
    assert final.content.endswith("A resposta corrigida.")

    # Audio channel: two items in the same order.
    audio_routed = StepOutput(content="A resposta corrigida.", audio=[object()])
    audio_final = harness._generate_apology(audio_routed)
    assert len(audio_final.audio) == 2
    assert audio_final.audio[0].transcript.startswith("Desculpe!")
    assert audio_final.audio[1].transcript == "A resposta corrigida."


def test_generate_apology_failure_keeps_answer(feedback_agents):
    """The main answer survives a remediation agent failure."""
    feedback_agents["remediation"].fail = True
    harness = _harness()

    routed = StepOutput(content="A resposta corrigida.")
    final = harness._generate_apology(routed)

    assert final.content == "A resposta corrigida."


# ---------------------------------------------------------------------
# Tests — turn n+1: completing (or dropping) the pending pair
# ---------------------------------------------------------------------

def test_positive_evaluation_completes_dpo_pair(db, feedback_agents):
    """Turn n+1 positive: the stored row gets the new answer as ``chosen``."""
    feedback_agents["satisfaction"].level = 1
    harness = _harness()

    session = _session_with_bad_answer()
    harness._process_feedback(session, "resposta errada!", session.session_state)
    record_id = session.interaction_assessment.pending.record_id
    session.interaction_assessment.pending.new_response = "A área é 1.500 hectares."

    # Turn n+1: the user confirms the new answer helped.
    feedback_agents["satisfaction"].level = 5
    needs_remediation = harness._process_feedback(
        session, "Agora sim, perfeito!", session.session_state
    )

    assert needs_remediation is False
    # The pending is closed, awaiting only the history finalizer.
    assert session.interaction_assessment.pending.closed is True

    record = db.query(NegativeFeedback).filter(NegativeFeedback.id == record_id).first()
    assert record.chosen == "A área é 1.500 hectares."
    assert record.rejected == "A área é 150 hectares."
    assert record.approved is True


def test_history_written_when_cycle_completes(db, feedback_agents):
    """The evaluation turn closes the pending; after the evaluation run is
    appended, the finalizer writes the cycle's ``history`` (up to 3 runs,
    from the frustration moment onward) onto the row and drops the pending."""
    feedback_agents["satisfaction"].level = 1
    harness = _harness()

    session = _session_with_bad_answer()
    session.session_state["recent_agent_runs"] = [
        {"user": "tudo certo até aqui?", "assistant": "Sim!", "tools": [], "messages": []}
    ]
    harness._process_feedback(session, "resposta errada!", session.session_state)
    record_id = session.interaction_assessment.pending.record_id
    session.interaction_assessment.pending.new_response = "A área é 1.500 hectares."

    # The frustration turn ends: its run is appended (as _persist_session does).
    session.runs.append(
        {"user": "resposta errada!", "assistant": "A área é 1.500 hectares."}
    )

    # Turn n+1: the user approves the remediation.
    feedback_agents["satisfaction"].level = 5
    harness._process_feedback(session, "Muito melhor!", session.session_state)
    pending = session.interaction_assessment.pending
    assert pending is not None and pending.closed is True

    # The evaluation run is appended, then the history is finalized.
    session.runs.append({"user": "Muito melhor!", "assistant": "A área é 1.500 hectares."})
    harness._finalize_pending_history(session)

    assert session.interaction_assessment.pending is None
    record = db.query(NegativeFeedback).filter(NegativeFeedback.id == record_id).first()
    assert len(record.history) == 2
    assert record.history[0] == {
        "user": "resposta errada!", "assistant": "A área é 1.500 hectares."
    }
    assert record.history[1] == {
        "user": "Muito melhor!", "assistant": "A área é 1.500 hectares."
    }


def test_failed_remediation_recorded_for_analysis(db, feedback_agents):
    """Turn n+1 negative: the row is NOT completed for training, but the
    failed new answer is kept (rejected_new + approved=False) so the
    repeated problem can be analyzed manually."""
    feedback_agents["satisfaction"].level = 1
    harness = _harness()

    session = _session_with_bad_answer()
    harness._process_feedback(session, "resposta errada!", session.session_state)
    record_id = session.interaction_assessment.pending.record_id
    session.interaction_assessment.pending.new_response = "A área é 999 hectares."

    # Turn n+1: still dissatisfied with the new answer.
    feedback_agents["satisfaction"].level = 2
    harness._process_feedback(session, "Piorou ainda!", session.session_state)

    assert session.interaction_assessment.pending.closed is True
    record = db.query(NegativeFeedback).filter(NegativeFeedback.id == record_id).first()
    assert record.chosen == ""
    assert record.approved is False
    assert record.rejected_new == "A área é 999 hectares."


def test_neutral_evaluation_leaves_row_untouched(db, feedback_agents):
    """A neutral evaluation claims nothing: the row keeps no approved key."""
    feedback_agents["satisfaction"].level = 1
    harness = _harness()

    session = _session_with_bad_answer()
    harness._process_feedback(session, "resposta errada!", session.session_state)
    record_id = session.interaction_assessment.pending.record_id
    session.interaction_assessment.pending.new_response = "A área é 1.500 hectares."

    # Turn n+1: the user moves on without evaluating.
    feedback_agents["satisfaction"].level = 3
    harness._process_feedback(session, "Me diz o clima de hoje?", session.session_state)

    assert session.interaction_assessment.pending.closed is True
    record = db.query(NegativeFeedback).filter(NegativeFeedback.id == record_id).first()
    assert record.chosen == ""
    assert record.approved is None  # neutral claims nothing


def test_negative_evaluation_marks_row_approved_false(db, feedback_agents):
    """Turn n+1 negative: no ``chosen``, the row is marked approved=False
    with the rejected new answer, pending drops."""
    feedback_agents["satisfaction"].level = 1
    harness = _harness()

    session = _session_with_bad_answer()
    harness._process_feedback(session, "resposta errada!", session.session_state)
    record_id = session.interaction_assessment.pending.record_id
    session.interaction_assessment.pending.new_response = "A área é 1.500 hectares."

    # Turn n+1: still dissatisfied with the new answer.
    feedback_agents["satisfaction"].level = 2
    harness._process_feedback(session, "Não, continua errado!", session.session_state)

    assert session.interaction_assessment.pending.closed is True
    record = db.query(NegativeFeedback).filter(NegativeFeedback.id == record_id).first()
    assert record.chosen == ""
    assert record.approved is False
    assert record.rejected_new == "A área é 1.500 hectares."


def test_new_frustration_after_cycle_closes(db, feedback_agents):
    """After a negative evaluation closes a cycle, a fresh frustration on a
    later turn opens a NEW pending pair with the newest bad exchange."""
    harness = _harness()

    # Turn n: first frustration (level 1).
    feedback_agents["satisfaction"].level = 1
    session = _session_with_bad_answer()
    harness._process_feedback(session, "resposta errada!", session.session_state)
    first_record_id = session.interaction_assessment.pending.record_id

    # Turn n+1: negative evaluation — cycle closes, pending consumed.
    feedback_agents["satisfaction"].level = 2
    harness._process_feedback(session, "Ainda não gostei!", session.session_state)
    assert session.interaction_assessment.pending.closed is True
    assert db.query(NegativeFeedback).count() == 1  # no new row this turn

    # Turn n+2: frustrated again over the latest bad exchange.
    session.runs.append(
        {"user": "Não, continua errado!",
         "assistant": "A área da fazenda continua 150 hectares."}
    )
    feedback_agents["satisfaction"].level = 1
    harness._process_feedback(session, "Continua errado!", session.session_state)

    pending = session.interaction_assessment.pending
    assert pending.record_id != first_record_id

    record = db.query(NegativeFeedback).filter(NegativeFeedback.id == pending.record_id).first()
    assert record.rejected == "A área da fazenda continua 150 hectares."


def test_positive_without_pending_still_saves_history(db, feedback_agents):
    """The classic SFT branch is untouched: positive satisfaction with no
    pending pair persists the clean-run history as PositiveFeedback."""
    feedback_agents["satisfaction"].level = 5
    harness = _harness()

    session = _session_with_bad_answer()
    session.session_state["recent_agent_runs"] = [
        {"user": "Qual a área da fazenda?", "assistant": "A área é 150 hectares.", "tools": [], "messages": []}
    ]
    harness._process_feedback(session, "valeu!", session.session_state)

    assert session.interaction_assessment.pending is None
    assert db.query(PositiveFeedback).filter(
        PositiveFeedback.grade == 5
    ).count() == 1
    assert db.query(NegativeFeedback).count() == 0


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

def _session_with_bad_answer():
    from semente.core.types import Session

    session = Session(user_id="test:dpo", session_id="test:dpo")
    # The bad exchange is the last history entry.
    session.runs = [
        {"user": "Qual a área da fazenda?", "assistant": "A área é 150 hectares."}
    ]
    return session