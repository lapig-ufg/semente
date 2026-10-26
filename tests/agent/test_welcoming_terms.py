"""The welcoming agent's terms stage — gated by features.terms-acceptance.

Builds the agent with a capturing backend (no LLM), so the terms copy, the
toolset and the stage switch are asserted on the ``AgentSpec`` the onboarding
agent is made of.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

import semente.agents.welcoming_agent as welcoming_agent_module
from semente.agents.welcoming_agent import (
    OnboardingStatus,
    _get_onboarding_status,
    _load_terms_text,
    build_welcoming_agent,
)
from semente.manifest import TermsConfig


class _CaptureBackend:
    """Returns the AgentSpec instead of building an engine agent."""

    def build_agent(self, spec):
        return spec


@pytest.fixture
def capture(monkeypatch):
    monkeypatch.setattr(welcoming_agent_module, "get_backend", lambda: _CaptureBackend())
    return lambda **kwargs: build_welcoming_agent(tts_enabled=False, **kwargs)


def _context(session_state):
    return SimpleNamespace(session_state=session_state)


def _tool_names(spec, session_state) -> set[str]:
    return {getattr(t, "name", getattr(t, "__name__", "")) for t in spec.tools(_context(session_state))}


# ---------------------------------------------------------------------
# Stage selection
# ---------------------------------------------------------------------
def test_terms_on_and_not_accepted_is_the_terms_stage():
    state = {"user_persona": {"name": "Ana", "role": "teacher"}}
    assert _get_onboarding_status(state, terms_enabled=True) == OnboardingStatus.NOT_ACCEPTED_TERMS


def test_terms_off_skips_straight_to_persona():
    state = {"user_persona": {"name": "Ana"}}
    assert _get_onboarding_status(state, terms_enabled=False) == OnboardingStatus.NOT_INFORMED_PERSONA


def test_terms_off_complete_persona_is_complete():
    state = {"user_persona": {"name": "Ana", "role": "teacher"}}
    assert _get_onboarding_status(state, terms_enabled=False) == OnboardingStatus.COMPLETE


# ---------------------------------------------------------------------
# Terms text loading
# ---------------------------------------------------------------------
def test_terms_file_is_resolved_relative_to_the_manifest(tmp_path):
    (tmp_path / "terms.md").write_text("  My Terms  ", encoding="utf-8")
    config = TermsConfig(enable=True, file="terms.md")
    assert _load_terms_text(config, tmp_path) == "My Terms"


def test_terms_enabled_without_file_fails_loudly(tmp_path):
    with pytest.raises(ValueError, match="no 'file' configured"):
        _load_terms_text(TermsConfig(enable=True), tmp_path)


def test_missing_terms_file_fails_loudly(tmp_path):
    config = TermsConfig(enable=True, file="missing.md")
    with pytest.raises(FileNotFoundError, match="missing.md"):
        _load_terms_text(config, tmp_path)


# ---------------------------------------------------------------------
# Prompt/toolset wiring
# ---------------------------------------------------------------------
def test_terms_stage_injects_url_and_reference_text(capture, tmp_path):
    (tmp_path / "terms.md").write_text("REFERENCE: be nice.", encoding="utf-8")
    spec = capture(
        terms=TermsConfig(enable=True, file="terms.md", url="https://x.test/terms"),
        app_name="Demo App",
        base_dir=tmp_path,
    )

    state = {"user_persona": {}}
    instructions = spec.instructions(_context(state))
    assert "Demo App" in instructions
    assert "https://x.test/terms" in instructions
    assert "REFERENCE: be nice." in instructions
    assert "accept_terms_and_conditions" in _tool_names(spec, state)


def test_terms_stage_without_url_asks_for_consent(capture, tmp_path):
    (tmp_path / "terms.md").write_text("REFERENCE.", encoding="utf-8")
    spec = capture(terms=TermsConfig(enable=True, file="terms.md"), base_dir=tmp_path)

    instructions = spec.instructions(_context({"user_persona": {}}))
    assert "no public Terms of Use link" in instructions


def test_terms_off_starts_on_persona_and_hides_the_terms_tool(capture):
    spec = capture(terms=None, app_name="Demo App")
    state = {"user_persona": {"name": "Ana"}}  # no terms_accepted at all

    instructions = spec.instructions(_context(state))
    assert "first contact" in instructions
    assert "already been accepted" not in instructions
    assert "Ana" in instructions

    tools = _tool_names(spec, state)
    assert "accept_terms_and_conditions" not in tools
    assert {"update_persona_name", "update_persona_role"} <= tools


def test_terms_on_closes_the_terms_step_in_the_persona_stage(capture, tmp_path):
    (tmp_path / "terms.md").write_text("TERMS", encoding="utf-8")
    spec = capture(
        terms=TermsConfig(enable=True, file="terms.md"), app_name="Demo App", base_dir=tmp_path
    )
    state = {"terms_accepted": True, "user_persona": {"name": "Ana"}}

    instructions = spec.instructions(_context(state))
    assert "already been accepted" in instructions
    assert "first contact" not in instructions
