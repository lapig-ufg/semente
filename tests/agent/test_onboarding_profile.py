"""Tests of the profile onboarding gate (issue #148).

Covers ``Harness._needs_onboarding``, which decides whether the user
goes to the welcoming agent or proceeds to the normal flow. The gate must
require the terms acceptance (only when ``features.terms-acceptance`` is
enabled), the name and the role — and, when all exist in the database, load
the profile into session_state so the agent can personalise the reply.

Ported from the upstream test suite, adapted to the Harness architecture: the
gate now takes ``(state, user_id)`` directly, so no StepInput doubles are
needed. Semente's DB defaults to SQLite (``tmp/agno.db``), so the fixture
creates the tables and cleans the two gate tables per test instead of standing
up a separate database.
"""

import datetime
from typing import Any

import pytest

from semente.core.harness import Harness
from semente.database.models import UserProfile, UserTermsAcceptance
from semente.database.session import SessionLocal, engine
from semente.services.session_migration import CURRENT_SCHEMA_VERSION
from semente.manifest import Manifest, TermsConfig


UID = "test:onboarding:5562900000000"


def _agent(features: dict[str, Any] | None = None) -> Harness:
    """A harness with the terms gate enabled (the pre-feature behavior)."""
    if features is None:
        features = {"terms-acceptance": TermsConfig(enable=True)}
    return Harness(
        agent=object(),
        welcoming_agent=object(),
        manifest=Manifest(name="test-app", features=features),
    )


# ---------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------
@pytest.fixture
def db():
    """Clean DB session before and after each test."""
    UserProfile.metadata.create_all(bind=engine)
    db_session = SessionLocal()
    _cleanup(db_session)
    yield db_session
    _cleanup(db_session)
    db_session.close()


def _cleanup(db_session) -> None:
    db_session.query(UserProfile).filter(UserProfile.user_id == UID).delete()
    db_session.query(UserTermsAcceptance).filter(UserTermsAcceptance.user_id == UID).delete()
    db_session.commit()


def _accept_terms(db_session) -> None:
    db_session.add(UserTermsAcceptance(
        user_id=UID, accepted=True, accepted_at=datetime.datetime.utcnow(),
    ))
    db_session.commit()


def _save_profile(db_session, name=None, role=None) -> None:
    db_session.add(UserProfile(user_id=UID, name=name, role=role))
    db_session.commit()


# ---------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------
def test_no_user_id_requires_onboarding(db):
    """No identifier: no way to query the database — fail safe."""
    state: dict[str, Any] = {}
    assert _agent()._needs_onboarding(state, None) is True


def test_new_user_requires_onboarding(db):
    """Nothing in the database, nothing in the session."""
    state: dict[str, Any] = {}
    assert _agent()._needs_onboarding(state, UID) is True


def test_terms_accepted_without_profile_requires_onboarding(db):
    """The classic bug: accepted the terms and would pass without identifying."""
    _accept_terms(db)
    state: dict[str, Any] = {}
    assert _agent()._needs_onboarding(state, UID) is True
    assert state["terms_accepted"] is True  # the acceptance was recognized


def test_incomplete_profile_requires_onboarding(db):
    """Gave the name and vanished before the role."""
    _accept_terms(db)
    _save_profile(db, name="João")
    state: dict[str, Any] = {}
    assert _agent()._needs_onboarding(state, UID) is True


def test_complete_profile_releases_and_loads_into_session(db):
    """The case issue #148 exists to solve.

    A user who already went through onboarding comes back in a brand new,
    empty session. The gate must recognize them from the database AND hand
    the profile to the agent.
    """
    _accept_terms(db)
    _save_profile(db, name="João", role="Producer")
    state: dict[str, Any] = {}

    assert _agent()._needs_onboarding(state, UID) is False

    assert state["user_persona"]["name"] == "João"
    assert state["user_persona"]["role"] == "Producer"


def test_complete_session_skips_the_database(db):
    """Performance shortcut: with everything in the session, no DB query.

    Nothing was written to the database in this test. If the gate queried it,
    it would find no profile and return True.
    """
    state: dict[str, Any] = {
        "terms_accepted": True,
        "user_persona": {"name": "João", "role": "Producer"},
    }
    assert _agent()._needs_onboarding(state, UID) is False


def test_session_does_not_overwrite_recently_saved_name(db):
    """The tool just changed the name in the session; the DB still has the old one."""
    _accept_terms(db)
    _save_profile(db, name="João", role="Producer")
    state: dict[str, Any] = {"user_persona": {"name": "Zé do Pasto"}}

    assert _agent()._needs_onboarding(state, UID) is False
    assert state["user_persona"]["name"] == "Zé do Pasto"
    assert state["user_persona"]["role"] == "Producer"


def test_persona_sentinel_in_db_incomplete_requires_onboarding(db):
    """A persona holding the schema sentinel value does not count as filled.

    `UserPersona` defaults to "Not yet known", so a persona built from
    the schema looks filled but is not. With no DB profile, onboarding is
    still required.
    """
    _accept_terms(db)
    state: dict[str, Any] = {
        "user_persona": {"name": "Not yet known", "role": "Not yet known"},
    }
    assert _agent()._needs_onboarding(state, UID) is True


def test_sentinel_in_session_is_filled_from_db(db):
    """Sentinel in the session + complete profile in the DB: release and cure the session.

    The gate must recognize the sentinel is not a real name, fetch the DB
    profile and overwrite the sentinel fields — not just fill missing keys.
    """
    _accept_terms(db)
    _save_profile(db, name="João", role="Producer")
    state: dict[str, Any] = {
        "user_persona": {"name": "Not yet known", "role": "Not yet known"},
    }

    assert _agent()._needs_onboarding(state, UID) is False
    assert state["user_persona"]["name"] == "João"
    assert state["user_persona"]["role"] == "Producer"


def test_partial_profile_sentinel_is_filled_without_wiping_session(db):
    """Real name in the session + sentinel role: the DB fills only the role."""
    _accept_terms(db)
    _save_profile(db, name="João", role="Technician")
    state: dict[str, Any] = {
        "user_persona": {"name": "Zé do Pasto", "role": "Not yet known"},
    }

    assert _agent()._needs_onboarding(state, UID) is False
    assert state["user_persona"]["name"] == "Zé do Pasto"
    assert state["user_persona"]["role"] == "Technician"


def test_old_state_is_migrated_without_breaking(db):
    """An old (pre-schema_version) session state is migrated in place, not rejected."""
    _accept_terms(db)
    _save_profile(db, name="João", role="Producer")
    state: dict[str, Any] = {
        "terms_accepted": True,
        "user_persona": {"name": "Not yet known", "role": "Not yet known"},
        "some_legacy_flag": True,
    }

    assert _agent()._needs_onboarding(state, UID) is False
    assert state["workflow_state"]["schema_version"] == CURRENT_SCHEMA_VERSION
    assert state["some_legacy_flag"] is True
    assert state["user_persona"]["name"] == "João"


# ---------------------------------------------------------------------
# features.terms-acceptance (off by default)
# ---------------------------------------------------------------------
def test_terms_disabled_releases_without_acceptance_row(db):
    """Terms off: a complete profile is enough, even with no acceptance row."""
    _save_profile(db, name="João", role="Producer")
    state: dict[str, Any] = {}

    assert _agent(features={})._needs_onboarding(state, UID) is False
    assert "terms_accepted" not in state  # no fake acceptance is written


def test_terms_disabled_still_requires_the_profile(db):
    """Terms off must not skip the persona gate."""
    state: dict[str, Any] = {}
    assert _agent(features={})._needs_onboarding(state, UID) is True
    assert state.get("terms_accepted") is None


def test_terms_disabled_session_profile_needs_no_database(db):
    """Terms off + persona in the session: released with no DB query at all."""
    state: dict[str, Any] = {"user_persona": {"name": "João", "role": "Producer"}}
    assert _agent(features={})._needs_onboarding(state, UID) is False


def test_terms_explicitly_disabled_config_behaves_like_absent(db):
    _save_profile(db, name="João", role="Producer")
    state: dict[str, Any] = {}

    features = {"terms-acceptance": TermsConfig(enable=False)}
    assert _agent(features=features)._needs_onboarding(state, UID) is False

# ---------------------------------------------------------------------
# features.onboarding (on by default)
# ---------------------------------------------------------------------
def test_onboarding_disabled_skips_the_gate_without_any_data(db):
    """Onboarding off: a brand-new anonymous user goes straight to the agent."""
    state: dict[str, Any] = {}
    harness = _agent(features={"onboarding": False})

    assert harness._needs_onboarding(state, None) is False
    assert state["workflow_state"] is not None  # session bootstrap still ran


def test_onboarding_disabled_overrides_terms_acceptance(db):
    features = {"onboarding": False, "terms-acceptance": TermsConfig(enable=True)}
    assert _agent(features=features)._needs_onboarding({}, UID) is False


def test_onboarding_enabled_by_default_and_explicitly(db):
    assert _agent(features={})._needs_onboarding({}, UID) is True
    assert _agent(features={"onboarding": True})._needs_onboarding({}, UID) is True
    assert _agent(features={"onboarding": {"enable": False}})._needs_onboarding({}, UID) is False
