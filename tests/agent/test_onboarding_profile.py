"""Tests of the profile onboarding gate (issue #148).

Covers ``Semente._needs_onboarding``, which decides whether the user
goes to the welcoming agent or proceeds to the normal flow. The gate must
require three things — terms acceptance, name and role — and, when all
exist in the database, load the profile into session_state so the agent can
personalise the reply.

Ported from pasto-legal `tests/workflows/test_onboarding_profile.py`
(PR #159 + tip fix `0816be3`), adapted to the Semente architecture:
the gate now takes ``(state, user_id)`` directly, so no StepInput doubles
are needed. Semente's DB defaults to SQLite (`tmp/agno.db`), so the fixture
creates the tables and cleans the two gate tables per test instead of
standing up a separate database.
"""

import datetime
from typing import Any

import pytest

from semente.core.semente_agent import Semente
from semente.database.models import UserProfile, UserTermsAcceptance
from semente.database.session import SessionLocal, engine
from semente.manifest import Manifest


UID = "test:onboarding:5562900000000"


def _agent() -> Semente:
    return Semente(
        agent=object(),
        welcoming_agent=object(),
        manifest=Manifest(name="test-app"),
    )


# ---------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------
@pytest.fixture
def db():
    """Clean DB session before and after each test."""
    UserProfile.metadata.create_all(bind=engine)
    sessao = SessionLocal()
    _limpar(sessao)
    yield sessao
    _limpar(sessao)
    sessao.close()


def _limpar(sessao) -> None:
    sessao.query(UserProfile).filter(UserProfile.user_id == UID).delete()
    sessao.query(UserTermsAcceptance).filter(UserTermsAcceptance.user_id == UID).delete()
    sessao.commit()


def _aceitar_termos(sessao) -> None:
    sessao.add(UserTermsAcceptance(
        user_id=UID, accepted=True, accepted_at=datetime.datetime.utcnow(),
    ))
    sessao.commit()


def _gravar_perfil(sessao, name=None, role=None) -> None:
    sessao.add(UserProfile(user_id=UID, name=name, role=role))
    sessao.commit()


# ---------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------
def test_sem_user_id_pede_onboarding(db):
    """No identifier: no way to query the database — fail safe."""
    estado: dict[str, Any] = {}
    assert _agent()._needs_onboarding(estado, None) is True


def test_usuario_novo_pede_onboarding(db):
    """Nothing in the database, nothing in the session."""
    estado: dict[str, Any] = {}
    assert _agent()._needs_onboarding(estado, UID) is True


def test_termos_aceitos_sem_perfil_pede_onboarding(db):
    """The classic bug: accepted the terms and would pass without identifying."""
    _aceitar_termos(db)
    estado: dict[str, Any] = {}
    assert _agent()._needs_onboarding(estado, UID) is True
    assert estado["terms_accepted"] is True  # the acceptance was recognized


def test_perfil_incompleto_pede_onboarding(db):
    """Gave the name and vanished before the role."""
    _aceitar_termos(db)
    _gravar_perfil(db, name="João")
    estado: dict[str, Any] = {}
    assert _agent()._needs_onboarding(estado, UID) is True


def test_perfil_completo_libera_e_carrega_na_sessao(db):
    """The case issue #148 exists to solve.

    A user who already went through onboarding comes back in a brand new,
    empty session. The gate must recognize them from the database AND hand
    the profile to the agent.
    """
    _aceitar_termos(db)
    _gravar_perfil(db, name="João", role="Produtor")
    estado: dict[str, Any] = {}

    assert _agent()._needs_onboarding(estado, UID) is False

    assert estado["user_persona"]["name"] == "João"
    assert estado["user_persona"]["role"] == "Produtor"


def test_sessao_completa_nao_consulta_o_banco(db):
    """Performance shortcut: with everything in the session, no DB query.

    Nothing was written to the database in this test. If the gate queried it,
    it would find no profile and return True.
    """
    estado: dict[str, Any] = {
        "terms_accepted": True,
        "user_persona": {"name": "João", "role": "Produtor"},
    }
    assert _agent()._needs_onboarding(estado, UID) is False


def test_sessao_nao_sobrescreve_nome_recem_gravado(db):
    """The tool just changed the name in the session; the DB still has the old one."""
    _aceitar_termos(db)
    _gravar_perfil(db, name="João", role="Produtor")
    estado: dict[str, Any] = {"user_persona": {"name": "Zé do Pasto"}}

    assert _agent()._needs_onboarding(estado, UID) is False
    assert estado["user_persona"]["name"] == "Zé do Pasto"
    assert estado["user_persona"]["role"] == "Produtor"


def test_persona_sentinela_no_banco_incompleto_pede_onboarding(db):
    """A persona holding the schema sentinel value does not count as filled.

    `UserPersona` defaults to "Ainda não conhecido", so a persona built from
    the schema looks filled but is not. With no DB profile, onboarding is
    still required.
    """
    _aceitar_termos(db)
    estado: dict[str, Any] = {
        "user_persona": {"name": "Ainda não conhecido", "role": "Ainda não conhecido"},
    }
    assert _agent()._needs_onboarding(estado, UID) is True


def test_sentinela_na_sessao_e_preenchida_pelo_banco(db):
    """Sentinel in the session + complete profile in the DB: release and cure the session.

    The gate must recognize the sentinel is not a real name, fetch the DB
    profile and overwrite the sentinel fields — not just fill missing keys.
    """
    _aceitar_termos(db)
    _gravar_perfil(db, name="João", role="Produtor")
    estado: dict[str, Any] = {
        "user_persona": {"name": "Ainda não conhecido", "role": "Ainda não conhecido"},
    }

    assert _agent()._needs_onboarding(estado, UID) is False
    assert estado["user_persona"]["name"] == "João"
    assert estado["user_persona"]["role"] == "Produtor"


def test_perfil_parcial_sentinela_e_preenchido_sem_apagar_sessao(db):
    """Real name in the session + sentinel role: the DB fills only the role."""
    _aceitar_termos(db)
    _gravar_perfil(db, name="João", role="Técnico")
    estado: dict[str, Any] = {
        "user_persona": {"name": "Zé do Pasto", "role": "Ainda não conhecido"},
    }

    assert _agent()._needs_onboarding(estado, UID) is False
    assert estado["user_persona"]["name"] == "Zé do Pasto"
    assert estado["user_persona"]["role"] == "Técnico"


def test_estado_antigo_e_migrado_sem_quebrar(db):
    """An old (pre-schema_version) session state is migrated in place, not rejected."""
    _aceitar_termos(db)
    _gravar_perfil(db, name="João", role="Produtor")
    estado: dict[str, Any] = {
        "terms_accepted": True,
        "user_persona": {"name": "Ainda não conhecido", "role": "Ainda não conhecido"},
        "some_legacy_flag": True,
    }

    assert _agent()._needs_onboarding(estado, UID) is False
    assert estado["workflow_state"]["schema_version"] == 1
    assert estado["some_legacy_flag"] is True
    assert estado["user_persona"]["name"] == "João"