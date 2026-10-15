"""Tests of the persona management branch of the feedback loop.

Covers ``Semente._manage_persona``: the structured PersonaUpdate application
and the failure safety — a failed persona manager agent must not crash the
turn (regression for the UnboundLocalError in the old failure handler, which
referenced the ``user_persona`` local before it was ever assigned) and must
leave the persona untouched.
"""

from types import SimpleNamespace
from typing import Any

import pytest

from semente.agents import persona_agent
from semente.backends.base import AgentTurn
from semente.core.semente_agent import Semente
from semente.manifest import Manifest
from semente.schemas.user_persona import CommunicationPreference, PersonaUpdate


class _RaisingManager:
    """Fake persona manager that crashes (agent outage)."""

    def run(self, agent_input):
        raise RuntimeError("persona manager down")


class _FakeManager:
    """Fake persona manager answering a canned structured update."""

    def __init__(self, update: PersonaUpdate):
        self._update = update
        self.inputs: list = []

    def run(self, agent_input) -> AgentTurn:
        self.inputs.append(agent_input)
        return AgentTurn(content="ok", structured=self._update.model_dump())


@pytest.fixture
def agente() -> Semente:
    return Semente(
        agent=object(),
        welcoming_agent=object(),
        manifest=Manifest(name="test-app"),
    )


def _estado(mood: dict[str, Any], persona: dict[str, Any] | None = None) -> dict[str, Any]:
    state: dict[str, Any] = {
        "user_persona": persona if persona is not None else {"name": "João", "role": "Produtor"},
        "user_mood": mood,
    }
    return state


# ---------------------------------------------------------------------
# Failure safety (the regression)
# ---------------------------------------------------------------------


def test_falha_do_agente_nao_explode_nem_corrompe_o_estado(monkeypatch, agente):
    """A persona manager outage must not crash the turn: persona untouched,
    mood cleared when it can no longer route to a remediation."""
    monkeypatch.setattr(persona_agent, "persona_manager_agent", _RaisingManager())

    estado = _estado(
        mood={"satisfaction": {"level": 4, "level_message": "satisfeito"}, "remediation": None}
    )

    # The old handler raised UnboundLocalError here and escaped the loop,
    # crashing the whole turn (found by the supervised_run flow tests).
    agente._manage_persona(None, "oi", estado)

    assert estado["user_mood"] is None
    assert estado["user_persona"]["name"] == "João"
    assert estado["user_persona"]["role"] == "Produtor"


def test_falha_com_satisfacao_baixa_sem_remediacao_mantem_o_humor(monkeypatch, agente):
    """Satisfaction < 3 with no remediation: the mood stays for the next run."""
    monkeypatch.setattr(persona_agent, "persona_manager_agent", _RaisingManager())

    estado = _estado(
        mood={"satisfaction": {"level": 1, "level_message": "frustrado"}, "remediation": None}
    )

    agente._manage_persona(None, "oi", estado)

    assert estado["user_mood"] is not None


# ---------------------------------------------------------------------
# Structured update application (the success path)
# ---------------------------------------------------------------------


def test_atualizacao_estruturada_aplica_na_persona(monkeypatch):
    """A valid PersonaUpdate lands in the persona and clears the mood."""
    update = PersonaUpdate(
        regionality="Sorriso - MT",
        communication_preferences=[
            CommunicationPreference(key="tom_de_voz", description="Respostas diretas")
        ],
    )
    manager = _FakeManager(update)
    monkeypatch.setattr(persona_agent, "persona_manager_agent", manager)

    agente = Semente(
        agent=object(),
        welcoming_agent=object(),
        manifest=Manifest(name="test-app"),
    )
    estado = _estado(
        mood={"satisfaction": {"level": 5, "level_message": "adorou"}, "remediation": None}
    )

    agente._manage_persona(None, "gostei muito da sua explicação", estado)

    assert estado["user_persona"]["regionality"] == "Sorriso - MT"
    prefs = estado["user_persona"]["communication_preferences"]
    assert prefs == [{"key": "tom_de_voz", "description": "Respostas diretas"}]
    assert estado["user_mood"] is None
    assert manager.inputs  # the manager saw the user's message