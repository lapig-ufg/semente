"""Pluggable input guardrails.

The contract and chain live in :mod:`semente.guardrails.base`; the
universally-safe built-ins live in :mod:`semente.guardrails.builtin`.

``semente.guardrails.redact_text`` / ``mask_text`` / ``sanitize_json`` route
through the **active chain** — the one composed from the app's
``DomainSpec.guardrails`` by the harness (``get_harness``), so channels,
tools, and persistence share exactly the same guards.

Usage::

    from semente.guardrails import EmailGuardrail, CardGuardrail

    domain_spec = DomainSpec(
        name="My App",
        tools=[...],
        guardrails=[EmailGuardrail(), CardGuardrail()],
    )
"""

from semente.guardrails.base import (
    GuardrailChain,
    GuardrailContext,
    GuardrailResult,
    InputGuardrail,
    RegexGuardrail,
    active_chain,
    mask_text,
    redact_text,
    sanitize_json,
    set_active_chain,
)
from semente.guardrails.builtin import CardGuardrail, EmailGuardrail

__all__ = [
    # contract
    "InputGuardrail",
    "GuardrailContext",
    "GuardrailResult",
    "RegexGuardrail",
    "GuardrailChain",
    # built-ins (opt-in)
    "EmailGuardrail",
    "CardGuardrail",
    # active-chain access
    "set_active_chain",
    "active_chain",
    "redact_text",
    "mask_text",
    "sanitize_json",
]