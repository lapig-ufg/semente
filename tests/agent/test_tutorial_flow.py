"""Tests of the tutorial flow — the supervisor routes, the checkpoint completes.

Covers the tutorial routing (``Semente._get_tutorial_status``), the
supervisor decision application in ``run()`` (forward / lesson / abandon /
fail-open), the step completion judged after a forwarded answer (callable
conditions and the ``tutorial_check_agent`` text conditions, both
fail-closed) with the congrats + next-lesson announcement appended, the
prompt compositions (the generic templates formatted with the domain's
``Tutorial``), the ``get_tutorial`` seam resolution, the tutorial-offer tool
(``set_tutorial_choice``) and the persistence rule: the database only ever
receives the FINAL outcome (declined or completed), while the in-flight step
lives exclusively in the session state.
"""

import datetime
import json
from types import SimpleNamespace
from typing import Any, List

import pytest

from semente.agents.tutorial_agent import (
    build_completion_announcement,
    build_geo_attachment_note,
    completion_payload,
    parse_completion_check,
    resolve_tutorial,
    tutorial_check_instructions,
    tutorial_instructions,
)
from semente.agents.welcoming_agent import (
    OnboardingStatus,
    _get_onboarding_status,
    tutorial_offer_menu,
)
from semente.backends.base import AgentInput, AgentTurn
from semente.core.semente_agent import Semente, TutorialStatus
from semente.database.models import (
    UserProfile,
    UserTermsAcceptance,
    UserTutorialProgress,
)
from semente.database.session import SessionLocal, engine
from semente.domain.base import DomainSpec, Tutorial, TutorialStep
from semente.manifest import Manifest
from semente.schemas.tutorial import CompletionCheck, TutorialDecision
from semente.schemas.workflow_state import (
    TUTORIAL_COMPLETED,
    WorkflowState,
    parse_tutorial_state,
)
from semente.tools.tutorial_tools import (
    mark_tutorial_completed,
    set_tutorial_choice,
)


UID = "test:tutorial:5562900000000"

NORMAL_REPLY = "resposta normal"
OFFER_REPLY = "pergunta do tutorial"


# ---------------------------------------------------------------------
# Fakes and helpers
# ---------------------------------------------------------------------


class _DecisionAgent:
    """Fake supervisor: answers canned decisions and records the input."""

    def __init__(self, decisions: List[TutorialDecision]):
        self._decisions = list(decisions)
        self.inputs: List[AgentInput] = []

    def run(self, agent_input: AgentInput) -> AgentTurn:
        self.inputs.append(agent_input)
        decision = self._decisions.pop(0) if self._decisions else TutorialDecision()
        return AgentTurn(content=decision.content, structured=decision.model_dump())


class _CheckAgent:
    """Fake checkpoint: answers canned verdicts and records the input."""

    def __init__(self, verdicts: List[CompletionCheck]):
        self._verdicts = list(verdicts)
        self.inputs: List[AgentInput] = []

    def run(self, agent_input: AgentInput) -> AgentTurn:
        self.inputs.append(agent_input)
        verdict = self._verdicts.pop(0) if self._verdicts else CompletionCheck()
        return AgentTurn(content="", structured=verdict.model_dump())


class _FailingSupervisor:
    """Fake supervisor that always crashes (evaluator outage)."""

    def run(self, agent_input: AgentInput):
        raise RuntimeError("evaluation exploded")


class _BlindSupervisor:
    """Fake supervisor without structured output (engine gap, e.g. bare)."""

    def run(self, agent_input: AgentInput) -> AgentTurn:
        return AgentTurn(content="resposta em prosa", structured=None)


class _FailingCheckAgent:
    """Fake checkpoint that always crashes (verdict outage: fail-closed)."""

    def run(self, agent_input: AgentInput):
        raise RuntimeError("checkpoint exploded")


class _BlindCheckAgent:
    """Fake checkpoint without structured output (fail-closed by design)."""

    def run(self, agent_input: AgentInput) -> AgentTurn:
        return AgentTurn(content="em prosa", structured=None)


class _FakeAgent:
    """Fake normal/welcoming agent: records the runs, answers canned content."""

    def __init__(self, content: str):
        self.inputs: List[AgentInput] = []
        self._content = content

    def run(self, agent_input: AgentInput) -> AgentTurn:
        self.inputs.append(agent_input)
        return AgentTurn(content=self._content)


def _tutorial(n_steps: int = 3, **overrides) -> Tutorial:
    """A fake ``Tutorial`` with N steps (str conditions by default).

    Every field carries its step index, so prompt assertions can point at
    the exact step being tested at its exact position.
    """
    steps = [
        TutorialStep(
            id=f"step{i + 1}",
            lesson=f"aula {i + 1}",
            forward_condition=f"caminho {i + 1}",
            complete_condition=f"condicao {i + 1}",
        )
        for i in range(n_steps)
    ]
    return Tutorial(steps=steps, **overrides)


def _nova_semente(
    decisions: List[TutorialDecision] | None = None,
    supervisor: Any | None = None,
    with_tutorial: bool = True,
    n_steps: int = 3,
    verdicts: List[CompletionCheck] | None = None,
    check_agent: Any | None = None,
) -> Semente:
    """A Semente with fake agents for full `run()` routing tests.

    Summarization/feedback are disabled: they are out of the tutorial flow's
    scope and would fire real LLM calls on the normal path (hermetic tests).
    """
    tutorial = _tutorial(n_steps) if with_tutorial else None
    if supervisor is None and with_tutorial:
        supervisor = _DecisionAgent(decisions or [])
    if check_agent is None and with_tutorial:
        check_agent = _CheckAgent(verdicts or [])
    return Semente(
        agent=_FakeAgent(NORMAL_REPLY),
        welcoming_agent=_FakeAgent(OFFER_REPLY),
        tutorial=tutorial,
        tutorial_agent=supervisor,
        tutorial_check_agent=check_agent,
        manifest=Manifest(
            name="test-app",
            features={"summarization": False, "feedback_workflow": False},
        ),
    )


def _mid_tutorial_state(step: Any) -> dict[str, Any]:
    """Session state of a user who completed onboarding and is mid-tutorial.

    ``step`` is the 0-based index (int or its decimal string) or the
    COMPLETED terminal sentinel.
    """
    return {
        "terms_accepted": True,
        "user_persona": {"name": "João", "role": "Produtor"},
        "workflow_state": {
            "schema_version": 1,
            "tutorial_state": str(step),
        },
    }


def _run_turn(
    session_state: dict,
    decisions: List[TutorialDecision] | None = None,
    supervisor: Any | None = None,
    with_tutorial: bool = True,
    n_steps: int = 3,
    verdicts: List[CompletionCheck] | None = None,
    check_agent: Any | None = None,
    **run_kwargs,
) -> tuple[Semente, Any]:
    """One pipeline turn with fake agents; returns (agent, final output)."""
    agente = _nova_semente(
        decisions,
        supervisor,
        with_tutorial=with_tutorial,
        n_steps=n_steps,
        verdicts=verdicts,
        check_agent=check_agent,
    )
    run_kwargs.setdefault("user_id", UID)
    run_kwargs.setdefault("session_id", "s1")
    run_kwargs.setdefault("input", "oi")
    final = agente.run(session_state=session_state, **run_kwargs)
    return agente, final


@pytest.fixture
def db():
    """Clean DB session before and after each test."""
    UserProfile.metadata.create_all(bind=engine)
    UserTutorialProgress.metadata.create_all(bind=engine)
    sessao = SessionLocal()
    _limpar(sessao)
    yield sessao
    _limpar(sessao)
    sessao.close()


def _limpar(sessao) -> None:
    sessao.query(UserProfile).filter(UserProfile.user_id == UID).delete()
    sessao.query(UserTermsAcceptance).filter(UserTermsAcceptance.user_id == UID).delete()
    sessao.query(UserTutorialProgress).filter(UserTutorialProgress.user_id == UID).delete()
    sessao.commit()


def _aceitar_termos(sessao) -> None:
    sessao.add(
        UserTermsAcceptance(user_id=UID, accepted=True, accepted_at=datetime.datetime.utcnow())
    )
    sessao.commit()


def _gravar_perfil(sessao, name="João", role="Produtor") -> None:
    sessao.add(UserProfile(user_id=UID, name=name, role=role))
    sessao.commit()


# ---------------------------------------------------------------------
# get_tutorial seam resolution
# ---------------------------------------------------------------------


def test_sem_get_tutorial_resolve_none():
    """A domain without get_tutorial disables the feature (no spec)."""
    assert resolve_tutorial(DomainSpec(name="x"), Manifest(name="x")) is None


def test_get_tutorial_e_aplicado():
    """get_tutorial returning a Tutorial wires it (any step count)."""
    spec = DomainSpec(name="x", get_tutorial=lambda: _tutorial(4))

    parsed = resolve_tutorial(spec, Manifest(name="x"))

    assert parsed is not None
    assert len(parsed.steps) == 4
    assert parsed.steps[0].id == "step1"


def test_feature_tutorial_off_no_manifest_desabilita():
    """features.tutorial=false wins over get_tutorial: the feature is off."""
    spec = DomainSpec(name="x", get_tutorial=lambda: _tutorial(3))

    parsed = resolve_tutorial(spec, Manifest(name="x", features={"tutorial": False}))

    assert parsed is None


def test_getter_mal_configurado_desabilita_com_seguranca():
    """A getter that fails or returns no steps disables the feature instead of crashing."""
    spec = DomainSpec(name="x", get_tutorial=lambda: 1 / 0)
    assert resolve_tutorial(spec, Manifest(name="x")) is None

    vazio = DomainSpec(name="x", get_tutorial=lambda: Tutorial(steps=[]))
    assert resolve_tutorial(vazio, Manifest(name="x")) is None

    nada = DomainSpec(name="x", get_tutorial=lambda: None)
    assert resolve_tutorial(nada, Manifest(name="x")) is None


# ---------------------------------------------------------------------
# Routing: where the user stands in the tutorial flow
# ---------------------------------------------------------------------


def test_recebe_a_oferta_como_primeira_interacao(db):
    """Accepted terms + full profile in the database, fresh session: the
    welcoming agent asks the tutorial offer (first time only)."""
    _aceitar_termos(db)
    _gravar_perfil(db)

    agente = _nova_semente()
    final = agente.run(user_id=UID, session_id="s1", input="oi", session_state={})

    assert final.content == OFFER_REPLY
    assert agente.agent.inputs == []  # the normal agent was not reached
    assert agente.tutorial_agent.inputs == []  # neither the supervisor
    assert agente.welcoming_agent.inputs  # the welcoming agent asked


def test_sem_tutorial_configurado_vai_direto_ao_fluxo_normal(db):
    """No Tutorial spec: the feature is fully off — DONE without the DB,
    the welcoming agent never asks an offer."""
    _aceitar_termos(db)
    _gravar_perfil(db)

    agente = _nova_semente(with_tutorial=False)

    assert agente._get_tutorial_status({}, UID) is TutorialStatus.DONE

    final = agente.run(user_id=UID, session_id="s1", input="oi", session_state={})
    assert final.content == NORMAL_REPLY
    assert agente.welcoming_agent.inputs == []
    assert agente.tutorial_agent is None


def test_decisao_final_no_banco_libera_mesmo_apos_reset(db):
    """Declined/completed tutorial row in the database: never asked again."""
    _aceitar_termos(db)
    _gravar_perfil(db)
    db.add(
        UserTutorialProgress(
            user_id=UID, completed=True, completed_at=datetime.datetime.utcnow()
        )
    )
    db.commit()

    estado: dict[str, Any] = {}
    agente = _nova_semente()

    assert agente._get_tutorial_status(estado, UID) is TutorialStatus.DONE
    assert estado["workflow_state"]["tutorial_state"] == TUTORIAL_COMPLETED

    final = agente.run(user_id=UID, session_id="s1", input="oi", session_state={})
    assert final.content == NORMAL_REPLY
    assert agente.welcoming_agent.inputs == []


def test_em_andamento_resolve_pela_sessao_sem_consultar_banco(db):
    """Mid-tutorial states resolve from the session state only (fast path).

    Nothing was written to the database in this test: a lookup would find
    none and (wrongly) re-offer the tutorial.
    """
    agente = _nova_semente()

    assert agente._get_tutorial_status(_mid_tutorial_state(0), UID) is TutorialStatus.RUNNING
    assert agente._get_tutorial_status(_mid_tutorial_state(1), UID) is TutorialStatus.RUNNING
    assert agente._get_tutorial_status(_mid_tutorial_state(2), UID) is TutorialStatus.RUNNING
    assert agente._get_tutorial_status(_mid_tutorial_state(TUTORIAL_COMPLETED), UID) is TutorialStatus.DONE


def test_indice_fora_do_limite_nao_trava_o_usuario(db):
    """A persisted index beyond the spec's step count (the Tutorial
    changed since) is not RUNNING: the user is not trapped — with no
    database row the flow simply re-offers."""
    agente = _nova_semente(n_steps=3)

    assert agente._get_tutorial_status(_mid_tutorial_state(9), UID) is TutorialStatus.UNDECIDED


def test_sessao_onboardada_sem_decisao_recebe_oferta(db):
    """Complete profile in the session, no tutorial decision (fresh user of
    the tutorial flow): the welcoming agent asks the offer."""
    estado: dict[str, Any] = {
        "terms_accepted": True,
        "user_persona": {"name": "João", "role": "Produtor"},
    }
    agente, final = _run_turn(estado)

    assert final.content == OFFER_REPLY
    assert agente.agent.inputs == []
    assert agente.tutorial_agent.inputs == []


# ---------------------------------------------------------------------
# Supervisor decisions applied by the pipeline
# ---------------------------------------------------------------------


def test_no_caminho_repassa_mensagem_ao_agente_normal():
    """Right path: the normal agent answers with the real work."""
    agente, final = _run_turn(
        _mid_tutorial_state(0),
        decisions=[TutorialDecision(forward=True)],
        verdicts=[CompletionCheck(step_completed=False)],
    )

    assert final.content == NORMAL_REPLY
    assert len(agente.tutorial_agent.inputs) == 1
    assert len(agente.agent.inputs) == 1
    assert len(agente.tutorial_check_agent.inputs) == 1  # the checkpoint judged
    assert agente.welcoming_agent.inputs == []


def test_fora_do_caminho_responde_com_a_licao():
    """Off track: the lesson is the reply; the normal agent is not reached."""
    licao = "Vamos começar! Envie a localização da propriedade."
    agente, final = _run_turn(
        _mid_tutorial_state(0),
        decisions=[TutorialDecision(forward=False, content=licao)],
    )

    assert final.content == licao
    assert agente.agent.inputs == []
    assert agente.tutorial_check_agent.inputs == []  # no reply, no checkpoint


def test_licao_marcada_como_entregue():
    """A non-forward reply marks the current step's lesson as delivered."""
    estado = _mid_tutorial_state(0)
    _run_turn(estado, decisions=[TutorialDecision(forward=False, content="aula")])

    workflow = estado["workflow_state"]
    assert workflow["tutorial_state"] == "0"
    assert workflow["tutorial_intro_sent"] is True


def test_checkpoint_completa_e_anuncia_o_proximo_passo():
    """A met condition after the forwarded reply: advance + announcement.

    The reply is the real answer PLUS the congrats with the next step's
    lesson (the new step is born lesson-delivered).
    """
    estado = _mid_tutorial_state(0)
    agente, final = _run_turn(
        estado,
        decisions=[TutorialDecision(forward=True)],
        verdicts=[CompletionCheck(step_completed=True)],
    )

    workflow = estado["workflow_state"]
    assert workflow["tutorial_state"] == "1"
    assert workflow["tutorial_intro_sent"] is True
    assert final.content.startswith(NORMAL_REPLY)
    assert "aula 2" in final.content  # the next step's lesson, announced


def test_checkpoint_negativo_nao_avanca():
    verdict = "condicao não satisfeita"
    estado = _mid_tutorial_state(0)
    agente, final = _run_turn(
        estado,
        decisions=[TutorialDecision(forward=True)],
        verdicts=[CompletionCheck(step_completed=False)],
    )

    assert estado["workflow_state"]["tutorial_state"] == "0"
    assert final.content == NORMAL_REPLY  # no announcement appended
    assert verdict not in final.content


def test_ultimo_passo_conclui_e_grava_no_banco(db):
    """The last step completed: final state, the closing appended, one row."""
    estado = _mid_tutorial_state(2)
    _, final = _run_turn(
        estado,
        decisions=[TutorialDecision(forward=True)],
        verdicts=[CompletionCheck(step_completed=True)],
    )

    assert estado["workflow_state"]["tutorial_state"] == TUTORIAL_COMPLETED
    assert final.content.startswith(NORMAL_REPLY)
    assert "finishing ALL the steps" in final.content  # the generic closing

    registro = (
        db.query(UserTutorialProgress).filter(UserTutorialProgress.user_id == UID).one()
    )
    assert registro.completed is True


def test_condicao_callable_recebe_sessao_texto_e_resposta():
    """A callable condition gets (session_state, user_text, agent_reply)."""
    received: dict[str, Any] = {}

    def condition(session_state, user_text, agent_reply):
        received.update(state=session_state, text=user_text, reply=agent_reply)
        return True

    estado = _mid_tutorial_state(0)
    semente = _nova_semente(decisions=[TutorialDecision(forward=True)])
    semente.tutorial.steps[0].complete_condition = condition
    final = semente.run(
        user_id=UID, session_id="s1", input="manda a localização", session_state=estado
    )

    assert received["state"] is estado  # the live session state
    assert received["text"] == "manda a localização"
    assert received["reply"] == NORMAL_REPLY
    assert estado["workflow_state"]["tutorial_state"] == "1"
    assert estado["workflow_state"]["tutorial_intro_sent"] is True
    assert "aula 2" in final.content
    assert semente.tutorial_check_agent.inputs == []  # callables skip the checkpoint


def test_condicao_callable_negativa_nao_avanca():
    estado = _mid_tutorial_state(0)
    semente = _nova_semente(decisions=[TutorialDecision(forward=True)])
    semente.tutorial.steps[0].complete_condition = lambda s, u, r: False
    semente.run(user_id=UID, session_id="s1", input="oi", session_state=estado)

    assert estado["workflow_state"]["tutorial_state"] == "0"
    assert estado["workflow_state"].get("tutorial_intro_sent", False) is False  # untouched on forwards


def test_condicao_callable_com_erro_nao_avanca():
    estado = _mid_tutorial_state(0)
    semente = _nova_semente(decisions=[TutorialDecision(forward=True)])

    def quebrada(session_state, user_text, agent_reply):
        raise RuntimeError("state lookup exploded")

    semente.tutorial.steps[0].complete_condition = quebrada
    semente.run(user_id=UID, session_id="s1", input="oi", session_state=estado)

    assert estado["workflow_state"]["tutorial_state"] == "0"


def test_checkpoint_quiado_nao_avanca_fail_closed():
    """Checkpoint outage / blind engine: not completed, the user keeps going."""
    estado = _mid_tutorial_state(0)
    semente = _nova_semente(decisions=[TutorialDecision(forward=True)], check_agent=_FailingCheckAgent())
    semente.run(user_id=UID, session_id="s1", input="oi", session_state=estado)
    assert estado["workflow_state"]["tutorial_state"] == "0"

    estado2 = _mid_tutorial_state(0)
    semente2 = _nova_semente(decisions=[TutorialDecision(forward=True)], check_agent=_BlindCheckAgent())
    semente2.run(user_id=UID, session_id="s1", input="oi", session_state=estado2)
    assert estado2["workflow_state"]["tutorial_state"] == "0"


def test_condicao_textual_sem_checkpoint_agent_nao_avanca():
    """No checkpoint built (text condition): fail-closed with a log."""
    estado = _mid_tutorial_state(0)
    semente = _nova_semente(decisions=[TutorialDecision(forward=True)], check_agent=None)
    semente.run(user_id=UID, session_id="s1", input="oi", session_state=estado)

    assert estado["workflow_state"]["tutorial_state"] == "0"


def test_tutorial_de_dois_passos_conclui_no_ultimo(db):
    """A 2-step tutorial: the second completion closes it.

    The step count comes from the Tutorial — any length advances the same
    way (0 -> 1 -> COMPLETED).
    """
    estado = _mid_tutorial_state(0)
    _run_turn(
        estado,
        decisions=[TutorialDecision(forward=True)],
        verdicts=[CompletionCheck(step_completed=True)],
        n_steps=2,
    )
    assert estado["workflow_state"]["tutorial_state"] == "1"

    _run_turn(
        estado,
        decisions=[TutorialDecision(forward=True)],
        verdicts=[CompletionCheck(step_completed=True)],
        n_steps=2,
    )

    assert estado["workflow_state"]["tutorial_state"] == TUTORIAL_COMPLETED

    registro = (
        db.query(UserTutorialProgress).filter(UserTutorialProgress.user_id == UID).one()
    )
    assert registro.completed is True


def test_tutorial_de_quatro_passos_avanca_um_por_vez():
    """A 4-step tutorial: every completed step advances exactly one."""
    estado = _mid_tutorial_state(0)

    for esperado in (1, 2, 3):
        # O spec de 4 passos em CADA turno (o helper reconstrói a semente).
        _run_turn(
            estado,
            decisions=[TutorialDecision(forward=True)],
            verdicts=[CompletionCheck(step_completed=True)],
            n_steps=4,
        )
        assert estado["workflow_state"]["tutorial_state"] == str(esperado)

    _run_turn(
        estado,
        decisions=[TutorialDecision(forward=True)],
        verdicts=[CompletionCheck(step_completed=True)],
        n_steps=4,
    )

    assert estado["workflow_state"]["tutorial_state"] == TUTORIAL_COMPLETED


def test_abandono_marca_como_concluido(db):
    """Leaving early is a final outcome: close and never offer again."""
    estado = _mid_tutorial_state(0)
    _, final = _run_turn(
        estado,
        decisions=[TutorialDecision(abandon_tutorial=True, content="tudo bem!")],
    )

    assert final.content == "tudo bem!"
    assert estado["workflow_state"]["tutorial_state"] == TUTORIAL_COMPLETED

    registro = (
        db.query(UserTutorialProgress).filter(UserTutorialProgress.user_id == UID).one()
    )
    assert registro.completed is True


def test_supervisor_com_falha_faz_forward():
    """Evaluator outage: the normal agent runs (the user is never stuck)."""
    agente, final = _run_turn(_mid_tutorial_state(0), supervisor=_FailingSupervisor())

    assert final.content == NORMAL_REPLY
    assert len(agente.agent.inputs) == 1


def test_supervisor_sem_estruturada_faz_forward():
    """No structured decision (engine gap): fail-open forward."""
    agente, final = _run_turn(_mid_tutorial_state(0), supervisor=_BlindSupervisor())

    assert final.content == NORMAL_REPLY
    assert len(agente.agent.inputs) == 1


def test_supervisor_ausente_faz_forward():
    """Supervisor never built (a `Tutorial` without an evaluator): fail-open.

    Whatever the routing (RUNNING), no evaluator means the normal agent
    answers — with a warning instead of an error every turn.
    """
    semente = Semente(
        agent=_FakeAgent(NORMAL_REPLY),
        welcoming_agent=_FakeAgent(OFFER_REPLY),
        tutorial=_tutorial(3),
        tutorial_agent=None,
        manifest=Manifest(
            name="test-app",
            features={"summarization": False, "feedback_workflow": False},
        ),
    )
    final = semente.run(
        user_id=UID, session_id="s1", input="oi", session_state=_mid_tutorial_state(0)
    )

    assert final.content == NORMAL_REPLY


# ---------------------------------------------------------------------
# Supervisor prompt composition
# ---------------------------------------------------------------------


def _run_context(session_state: dict) -> SimpleNamespace:
    return SimpleNamespace(session_state=session_state)


def test_instrucoes_carregam_o_passo_o_historico_e_o_status_da_licao():
    """The instructions carry the current step position, the lesson flag and history."""
    estado = _mid_tutorial_state(1)
    estado["history_context"] = "<iterações>...</iterações>"

    instrucoes = tutorial_instructions(_run_context(estado), _tutorial(3))

    assert "tutorial_progress: 2/3 (id: step2)" in instrucoes
    assert "lesson_delivered: no" in instrucoes
    assert "<iterações>...</iterações>" in instrucoes
    assert "aula 2" in instrucoes  # the step's own lesson
    assert "caminho 2" in instrucoes  # the step's forward condition


def test_supervisor_nao_carrega_a_condicao_de_conclusao():
    """completion_condition is the checkpoint's business — never in the supervisor."""
    instrucoes = tutorial_instructions(_run_context(_mid_tutorial_state(0)), _tutorial(3))

    assert "condicao" not in instrucoes  # the steps' str conditions
    assert "COMPLETION" not in instrucoes.upper()
    assert "aula 2" not in instrucoes  # no next-lesson injection either


def test_instrucoes_sem_estado_caem_no_primeiro_passo():
    """An empty state grades as the first step with the lesson pending."""
    instrucoes = tutorial_instructions(_run_context({}), _tutorial(3))

    assert "tutorial_progress: 1/3 (id: step1)" in instrucoes
    assert "lesson_delivered: no" in instrucoes


def test_instrucoes_carregam_os_fallbacks_padrao_do_yaml():
    """Without Tutorial.abandon, the generic yml default is used."""
    instrucoes = tutorial_instructions(_run_context(_mid_tutorial_state(0)), _tutorial(3))

    assert "no pressure" in instrucoes


def test_instrucoes_carregam_texts_customizados_do_tutorial():
    """Tutorial.abandon overrides land in the template."""
    tutorial = _tutorial(3, abandon="Sem problemas, até logo!")

    instrucoes = tutorial_instructions(_run_context(_mid_tutorial_state(0)), tutorial)

    assert "Sem problemas, até logo!" in instrucoes
    assert "no pressure" not in instrucoes


# ---------------------------------------------------------------------
# Checkpoint prompt + verdict + announcement
# ---------------------------------------------------------------------


def test_checkpoint_instrucoes_carregam_a_condicao_e_o_historico():
    """The checkpoint prompt embeds the current step's completion condition."""
    estado = _mid_tutorial_state(1)
    estado["history_context"] = "<iterações>...</iterações>"

    instrucoes = tutorial_check_instructions(_run_context(estado), _tutorial(3))

    assert "current_step: step2 (2/3)" in instrucoes
    assert "<completion_condition>\ncondicao 2" in instrucoes
    assert "<iterações>...</iterações>" in instrucoes


def test_checkpoint_nao_carrega_a_licao():
    """The checkpoint judges the condition — lesson/forward stay with the supervisor."""
    instrucoes = tutorial_check_instructions(_run_context(_mid_tutorial_state(0)), _tutorial(3))

    assert "aula 1" not in instrucoes.split("<completion_condition>")[0]
    assert "caminho 1" not in instrucoes


def _verdadeiro(agente_input: AgentInput) -> AgentTurn:
    return AgentTurn(content="", structured=CompletionCheck(step_completed=True).model_dump())


def test_verificacao_persa_do_veredito():
    """parse_completion_check: structured wins, everything else fails closed."""
    assert parse_completion_check(_verdadeiro(None)) is True
    assert parse_completion_check(AgentTurn(content="prosa", structured=None)) is False
    assert parse_completion_check(None) is False
    assert parse_completion_check(AgentTurn(content="", structured={})) is False


def test_payload_do_checkpoint_carrega_mensagem_e_resposta():
    payload = completion_payload("manda a localização", NORMAL_REPLY)

    assert "<user_message>\nmanda a localização\n</user_message>" in payload
    assert f"<assistant_reply>\n{NORMAL_REPLY}\n</assistant_reply>" in payload


def test_anuncio_do_proximo_passo():
    """On completion with a next step: the congrats template with its lesson."""
    anuncio = build_completion_announcement(_tutorial(3), _mid_tutorial_state(0))

    assert '"step1"' in anuncio
    assert "aula 2" in anuncio


def test_anuncio_do_ultimo_passo_usa_o_fechamento():
    """On the last step the announcement is the closing (custom override wins)."""
    anuncio_padrao = build_completion_announcement(_tutorial(2), _mid_tutorial_state(1))
    assert "finishing ALL the steps" in anuncio_padrao

    custom = _tutorial(2, closing="acabou, uso liberado!")
    anuncio_custom = build_completion_announcement(custom, _mid_tutorial_state(1))
    assert anuncio_custom == "acabou, uso liberado!"


# ---------------------------------------------------------------------
# Welcoming agent: tutorial-offer stage wiring
# ---------------------------------------------------------------------


def _estado_onboardado() -> dict[str, Any]:
    return {"terms_accepted": True, "user_persona": {"name": "João", "role": "Produtor"}}


def test_offer_menu_e_construido_dos_ids():
    """The default offer menu enumerates the step ids (no titles anymore)."""
    menu = tutorial_offer_menu(_tutorial(2))

    assert menu == "a guided tutorial in 2 steps: 1. step1 2. step2"


def test_onboarding_com_tutorial_pendente_e_estagio_da_oferta():
    """Complete profile + tutorial wired + no decision -> the offer stage."""
    assert (
        _get_onboarding_status(_estado_onboardado(), _tutorial(3)) is OnboardingStatus.NOT_DECIDED_TUTORIAL
    )


def test_onboarding_sem_tutorial_fica_completo_apos_perfil():
    """No Tutorial wired: persona complete is the end of onboarding."""
    assert _get_onboarding_status(_estado_onboardado()) is OnboardingStatus.COMPLETE
    assert _get_onboarding_status(_estado_onboardado(), None) is OnboardingStatus.COMPLETE


# ---------------------------------------------------------------------
# set_tutorial_choice tool
# ---------------------------------------------------------------------


def _run_context_tool(estado: dict, user_id: Any = None) -> SimpleNamespace:
    return SimpleNamespace(session_state=estado, user_id=user_id)


# NOTE: like every other tool in the project, `set_tutorial_choice` may
# replace ``run_context.session_state`` (when it starts empty), so tests
# read the state through the context — the same handle an engine observes.


def test_tool_aceita_inicia_o_primeiro_passo_sem_gravar_banco(db):
    """Accepting only starts the flow: no final row is ever written."""
    ctx = _run_context_tool({}, UID)

    set_tutorial_choice(True, ctx)

    workflow = ctx.session_state["workflow_state"]
    assert workflow["tutorial_state"] == "0"
    assert workflow["tutorial_intro_sent"] is False
    assert (
        db.query(UserTutorialProgress).filter(UserTutorialProgress.user_id == UID).first()
        is None
    )


def test_tool_recusa_grava_o_final_no_banco(db):
    """Declining is a final outcome: persisted so the offer never returns."""
    ctx = _run_context_tool({}, UID)

    set_tutorial_choice(False, ctx)

    workflow = ctx.session_state["workflow_state"]
    assert workflow["tutorial_state"] == TUTORIAL_COMPLETED

    registro = (
        db.query(UserTutorialProgress).filter(UserTutorialProgress.user_id == UID).one()
    )
    assert registro.completed is True


def test_marcar_concluido_persiste_e_muda_a_sessao(db):
    estado: dict[str, Any] = {}

    mark_tutorial_completed(estado, UID)

    assert estado["workflow_state"]["tutorial_state"] == TUTORIAL_COMPLETED
    assert estado["workflow_state"]["tutorial_intro_sent"] is True
    registro = (
        db.query(UserTutorialProgress).filter(UserTutorialProgress.user_id == UID).one()
    )
    assert registro.completed is True


def test_marcar_concluido_sem_user_id_fica_apenas_na_sessao(db):
    estado: dict[str, Any] = {}

    mark_tutorial_completed(estado, None)

    assert estado["workflow_state"]["tutorial_state"] == TUTORIAL_COMPLETED
    assert (
        db.query(UserTutorialProgress).filter(UserTutorialProgress.user_id == UID).count() == 0
    )


# ---------------------------------------------------------------------
# State serialization
# ---------------------------------------------------------------------


def test_estado_de_tutorial_sobrevive_ao_json():
    """The tutorial position round-trips through the session store's JSON."""
    workflow = WorkflowState(tutorial_state="1", tutorial_intro_sent=True)

    serializado = json.loads(json.dumps(workflow.model_dump()))

    assert serializado["tutorial_state"] == "1"
    assert serializado["tutorial_intro_sent"] is True
    assert parse_tutorial_state(serializado["tutorial_state"]) == "1"

    hidratado = WorkflowState.model_validate(serializado)
    assert hidratado.tutorial_state == "1"


def test_parse_do_estado_da_posicao():
    """The persisted position parses to None / the index / the sentinel."""
    assert parse_tutorial_state(None) is None
    assert parse_tutorial_state("") is None
    assert parse_tutorial_state("FIRST_STATE") is None  # old enum name: junk now
    assert parse_tutorial_state("-1") is None
    assert parse_tutorial_state("JUNK_STATE") is None
    assert parse_tutorial_state("2") == "2"
    assert parse_tutorial_state(1) == "1"
    assert parse_tutorial_state(TUTORIAL_COMPLETED) == TUTORIAL_COMPLETED


def test_geo_attachment_note_generico():
    """The supervisor's attachment note is a localized generic prompt key."""
    nota = build_geo_attachment_note()
    assert nota
    assert "geospatial" in nota.lower()
    assert "o usuário" not in nota  # no pt-BR leftover from the first attempt


def test_supervisor_ve_o_anexo_geo(monkeypatch):
    """Geo files in the run are announced to the text-only supervisor."""
    agente = _nova_semente([TutorialDecision(forward=True)])
    fake_file = SimpleNamespace(name="x.geojson")
    monkeypatch.setattr(
        agente, "_input_preprocessing", lambda *args, **kwargs: ("oi", [fake_file])
    )
    final = agente.run(
        user_id=UID,
        session_id="s1",
        input="oi",
        session_state=_mid_tutorial_state(0),
    )

    assert final.content == NORMAL_REPLY
    entrada = agente.tutorial_agent.inputs[-1].text
    assert "<geo_attachment>" in entrada
    assert "anexo" not in entrada  # the marker tag is language-neutral now