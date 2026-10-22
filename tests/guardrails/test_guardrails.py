"""Unit tests for the pluggable input-guardrail interface
(``semente/guardrails``): the contract, the regex base, the builtins, the
chain composition, blocking, masking, and JSON sanitization. Fully
deterministic — no LLM/network.
"""

import logging
import re

import pytest

from semente import DomainSpec
from semente.core.harness import Harness
from semente.core.types import Session
from semente.manifest import Manifest
from semente.guardrails import (
    CardGuardrail,
    EmailGuardrail,
    GuardrailChain,
    GuardrailContext,
    GuardrailResult,
    RegexGuardrail,
    active_chain,
    mask_text,
    redact_text,
    sanitize_json,
    set_active_chain,
)


# --- RegexGuardrail: the base users subclass ---

class PhoneGuardrail(RegexGuardrail):
    name = "phone"
    marker = "[PHONE_HIDDEN]"
    patterns = (re.compile(r"(?<!\d)\d{2}[ -]\d{4,5}[ -]?\d{4}(?!\d)"),)


def test_regex_guardrail_redacts():
    chain = GuardrailChain([PhoneGuardrail()])
    result = chain.redact(GuardrailContext(text="my phone is 62 99999-8888"))
    assert result.text == "my phone is [PHONE_HIDDEN]"
    assert result.removed == ["phone"]


def test_regex_guardrail_leaves_clean_text():
    chain = GuardrailChain([PhoneGuardrail()])
    result = chain.redact(GuardrailContext(text="I want the map of my farm"))
    assert result.text == "I want the map of my farm"
    assert result.removed == []


def test_regex_guardrail_validator_skips_non_sensitive():
    """A validator returning False keeps the match (e.g. a bare number)."""

    class StrictPhone(RegexGuardrail):
        name = "phone"
        marker = "[PHONE_HIDDEN]"
        patterns = (re.compile(r"(?<!\d)\d{2}[ -]\d{4}[ -]\d{4}(?!\d)"),)
        validators = (lambda full: full.startswith("62"),)

    guard = StrictPhone()
    assert guard.redact(GuardrailContext(text="call 11 3333-4444")).text == "call 11 3333-4444"
    assert guard.redact(GuardrailContext(text="call 62 3333-4444")).text == "call [PHONE_HIDDEN]"


def test_regex_guardrail_merges_overlapping_matches():
    """Overlapping patterns of the same guard collapse into one span."""

    class LooseGuard(RegexGuardrail):
        name = "loose"
        marker = "[X]"
        patterns = (
            re.compile(r"ab"),
            re.compile(r"b"),
        )

    result = LooseGuard().redact(GuardrailContext(text="ab"))
    assert result.text == "[X]"


def test_regex_guardrail_mask():
    chain = GuardrailChain([PhoneGuardrail()])
    assert chain.mask("my phone is 62 99999-8888") == "my phone is [hidden]"
    assert chain.mask("no pii here") == "no pii here"


def test_accepts_class_not_instance():
    chain = GuardrailChain([PhoneGuardrail])
    assert isinstance(chain.guardrails[0], PhoneGuardrail)


# --- Builtins ---

def test_email_guardrail():
    result = EmailGuardrail().redact(
        GuardrailContext(text="reach me at joao.silva@gmail.com, please")
    )
    assert result.text == "reach me at [EMAIL_HIDDEN], please"
    assert result.removed == ["email"]


def test_email_guardrail_clean():
    assert EmailGuardrail().redact(GuardrailContext(text="no @ sign here")).text == "no @ sign here"


def test_card_guardrail_luhn_valid():
    result = CardGuardrail().redact(GuardrailContext(text="card 4570 7318 2800 8591"))
    assert result.text == "card [CARD_HIDDEN]"
    assert result.removed == ["card"]


def test_card_guardrail_luhn_invalid_kept():
    result = CardGuardrail().redact(GuardrailContext(text="4570 7318 2800 8592"))
    assert result.text == "4570 7318 2800 8592"


def test_card_guardrail_brand_prefix():
    assert CardGuardrail().redact(GuardrailContext(text="4111111111111111")).text == "[CARD_HIDDEN]"


def test_card_guardrail_bare_number_ignored():
    """13-16 digits + Luhn is noise: 1 in 9 passes by chance."""
    assert CardGuardrail().redact(GuardrailContext(text="50857591629029")).text == "50857591629029"


# --- Chain composition ---

def test_chain_aggregates_removed_types_in_order():
    chain = GuardrailChain([PhoneGuardrail(), EmailGuardrail()])
    result = chain.redact(
        GuardrailContext(text="email joao@gmail.com and phone 62 99999-8888")
    )
    assert result.text == "email [EMAIL_HIDDEN] and phone [PHONE_HIDDEN]"
    assert result.removed == ["phone", "email"]


def test_empty_chain_is_identity():
    chain = GuardrailChain([])
    assert not chain.enabled
    result = chain.redact(GuardrailContext(text="my cpf is 710.768.971-18"))
    assert result.text == "my cpf is 710.768.971-18"
    assert chain.mask("email joao@gmail.com") == "email joao@gmail.com"
    assert chain.redact_text("email joao@gmail.com") == "email joao@gmail.com"


def test_chain_redact_text_convenience():
    chain = GuardrailChain([EmailGuardrail()])
    assert chain.redact_text("write to a@b.com") == "write to [EMAIL_HIDDEN]"


# --- Blocking ---

class BlockEverything(RegexGuardrail):
    name = "blocker"
    marker = "[X]"

    def redact(self, context: GuardrailContext):
        return GuardrailResult(
            text="[REDACTED]", removed=["blocker"], blocked=True,
            response="I cannot process this request.",
        )


def test_chain_reports_first_block():
    chain = GuardrailChain([PhoneGuardrail(), BlockEverything()])
    result = chain.redact(GuardrailContext(text="whatever"))
    assert result.blocked
    assert result.response == "I cannot process this request."
    assert result.text == "[REDACTED]"  # redaction of prior guards persists


def test_chain_no_block():
    chain = GuardrailChain([PhoneGuardrail()])
    assert not chain.redact(GuardrailContext(text="hi")).blocked


# --- GuardrailContext plumbing ---

def test_context_fields_reach_the_guard():
    seen = {}

    class Spy(RegexGuardrail):
        name = "spy"

        def redact(self, context: GuardrailContext):
            seen.update(
                source=context.source,
                user_id=context.user_id,
                state=context.session_state,
            )
            return GuardrailResult(text=context.text)

    GuardrailChain([Spy()]).redact(
        GuardrailContext(text="hi", session_state={"a": 1}, user_id="u1", source="media")
    )
    assert seen == {"source": "media", "user_id": "u1", "state": {"a": 1}}


# --- JSON sanitization ---

def test_chain_sanitize_json_recursive():
    chain = GuardrailChain([EmailGuardrail()])
    data = {"a": "mail a@b.com", "nested": ["c@d.com", 42, True, None], "k": "v"}
    out = chain.sanitize_json(data)
    assert out == {"a": "mail [EMAIL_HIDDEN]", "nested": ["[EMAIL_HIDDEN]", 42, True, None], "k": "v"}
    assert out["nested"][1] == 42 and out["nested"][3] is None


# --- Active chain (the module-level singleton channels reuse) ---

def test_active_chain_singleton():
    set_active_chain(None)
    assert active_chain() is None
    assert redact_text("a@b.com") == "a@b.com"   # identity before get_harness
    assert sanitize_json({"s": "a@b.com"}) == {"s": "a@b.com"}
    assert mask_text("a@b.com") == "a@b.com"

    chain = GuardrailChain([EmailGuardrail()])
    set_active_chain(chain)
    assert active_chain() is chain
    assert redact_text("a@b.com") == "[EMAIL_HIDDEN]"
    assert chain.sanitize_json({"s": "a@b.com"}) != {"s": "a@b.com"}
    assert "[hidden]" in mask_text("write to a@b.com")
    set_active_chain(None)


# --- DomainSpec carries the guards ---

def test_domain_spec_guardrails_field():
    spec = DomainSpec(name="app", guardrails=[EmailGuardrail])
    assert spec.guardrails == [EmailGuardrail]
    assert DomainSpec(name="app").guardrails == []


# --- Observability: the guardrail lifecycle in the logs ---

def test_chain_logs_clean_and_redacted(caplog):
    chain = GuardrailChain([EmailGuardrail()])
    with caplog.at_level(logging.DEBUG, logger="semente"):
        clean = chain.redact(GuardrailContext(text="hello"))
        hit = chain.redact(GuardrailContext(text="email a@b.com"))
    assert clean.text == "hello"
    assert "guardrail 'email': clean" in caplog.text
    assert hit.text == "email [EMAIL_HIDDEN]"
    assert "guardrail 'email': redacted (email)" in caplog.text


def test_chain_logs_block(caplog):
    with caplog.at_level(logging.DEBUG, logger="semente"):
        GuardrailChain([BlockEverything()]).redact(
            GuardrailContext(text="x", source="pipeline")
        )
    assert "guardrail 'blocker': BLOCKED the turn [source=pipeline]" in caplog.text


def test_chain_logs_no_guards(caplog):
    with caplog.at_level(logging.DEBUG, logger="semente"):
        GuardrailChain([]).redact(GuardrailContext(text="x"))
    assert "no guards" in caplog.text


def test_pipeline_summary_log(caplog):
    """One INFO summary per turn at the pipeline stage."""
    harness = Harness(
        agent=None,
        welcoming_agent=None,
        manifest=Manifest(name="logs"),
        guardrails=GuardrailChain([EmailGuardrail()]),
    )
    session = Session(user_id="u1", session_id="s1")

    with caplog.at_level(logging.DEBUG, logger="semente"):
        text, blocked = harness._run_input_guardrails("write to a@b.com", session)
    assert text == "write to [EMAIL_HIDDEN]" and blocked is None
    assert "guardrails[pipeline]: removed (email)" in caplog.text

    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger="semente"):
        text, blocked = harness._run_input_guardrails("nothing wrong here", session)
    assert "guardrails[pipeline]: 1 guard(s) ran — clean" in caplog.text

    caplog.clear()
    with caplog.at_level(logging.DEBUG, logger="semente"):
        text, blocked = harness._run_input_guardrails("send me this", session)
    assert text and blocked is None and "clean" in caplog.text


def test_pipeline_blocked_log(caplog):
    """A blocked guard short-circuits: refusal reply out, agent never runs."""
    harness = Harness(
        agent=None,
        welcoming_agent=None,
        manifest=Manifest(name="logs"),
        guardrails=GuardrailChain([EmailGuardrail(), BlockEverything()]),
    )
    session = Session(user_id="u1", session_id="s1")
    with caplog.at_level(logging.DEBUG, logger="semente"):
        text, blocked = harness._run_input_guardrails("send me this", session)
    assert blocked is not None and blocked.blocked
    assert "BLOCKED" in caplog.text
    assert "agent skipped" in caplog.text
    # The refusal reply is what would reach the user.
    assert blocked.response == "I cannot process this request."


def test_feature_toggle_silences_the_chain(caplog):
    harness = Harness(
        agent=None,
        welcoming_agent=None,
        manifest=Manifest(name="logs", features={"guardrails": False}),
        guardrails=GuardrailChain([EmailGuardrail()]),
    )
    session = Session(user_id="u1", session_id="s1")
    with caplog.at_level(logging.DEBUG, logger="semente"):
        text, blocked = harness._run_input_guardrails("email a@b.com", session)
    assert text == "email a@b.com" and blocked is None
    assert "feature off" in caplog.text


def test_media_stage_log(caplog):
    harness = Harness(
        agent=None,
        welcoming_agent=None,
        manifest=Manifest(name="logs"),
        guardrails=GuardrailChain([EmailGuardrail()]),
    )
    with caplog.at_level(logging.DEBUG, logger="semente"):
        clean = harness._run_media_guardrails("no pii text", "audio")
        redacted = harness._run_media_guardrails("mail a@b.com", "audio")
    assert clean == "no pii text" and redacted == "mail [EMAIL_HIDDEN]"
    assert "guardrails[media:audio]: removed (email)" in caplog.text