from semente.services.session_migration import CURRENT_SCHEMA_VERSION, migrate_session_state


def test_migrate_v0_to_v1_maintains_data():
    raw_state = {
        "user_persona": {"name": "Produtor Teste", "role": "Produtor"},
        "some_legacy_flag": True,
    }

    migrated = migrate_session_state(raw_state)

    assert migrated.get("workflow_state", {}).get("schema_version") == CURRENT_SCHEMA_VERSION
    assert migrated["user_persona"] == raw_state["user_persona"]
    assert migrated["some_legacy_flag"] is True
    assert "_legacy_data" in migrated


def test_migrate_drops_legacy_user_mood():
    raw_state = {
        "user_persona": {},
        "user_mood": {"satisfaction": {"level": 3}},
    }

    migrated = migrate_session_state(raw_state)

    assert "user_mood" not in migrated
    assert migrated.get("workflow_state", {}).get("schema_version") == CURRENT_SCHEMA_VERSION


def test_migrate_idempotency():
    raw_state = {
        "workflow_state": {"schema_version": CURRENT_SCHEMA_VERSION, "is_feedback_active": False},
        "user_persona": {},
        "_legacy_data": {},
    }

    migrated = migrate_session_state(raw_state)

    assert migrated == raw_state


def test_migrate_empty_state_resilience():
    raw_state = {}

    migrated = migrate_session_state(raw_state)

    assert migrated.get("workflow_state", {}).get("schema_version") == CURRENT_SCHEMA_VERSION
    assert isinstance(migrated.get("user_persona"), dict)
    assert isinstance(migrated.get("_legacy_data"), dict)


def test_migrate_does_not_mutate_input():
    raw_state = {"user_persona": {"name": "João"}}

    migrated = migrate_session_state(raw_state)

    assert "workflow_state" not in raw_state
    assert migrated is not raw_state
    assert migrated["user_persona"] == {"name": "João"}