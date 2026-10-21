"""Engine-neutral built-in guardrails, ready to import and mix.

These are **opt-in**: a guard only runs when the app declares it in
``DomainSpec.guardrails``. The universally-safe ones live here; anything
country- or domain-specific (documents, identifiers) ships with the domain —
Pasto Legal's Brazil PII set migrated to ``migrate-to-pasto-legal/``.
"""

from __future__ import annotations

import re

from semente.guardrails.base import GuardrailContext, GuardrailResult, RegexGuardrail

_NO_BOUNDARY_L = r"(?<!\d)(?<!\d[.,])"
_NO_BOUNDARY_R = r"(?!\d)(?![.,]\d)"

# --- E-mail ---
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")


class EmailGuardrail(RegexGuardrail):
    """Redacts e-mail addresses (format is self-evident — no validator)."""

    name = "email"
    marker = "[EMAIL_HIDDEN]"
    patterns = (_EMAIL_RE,)


# --- Credit card ---
# Two accepted forms, always complete: visual grouping (4-4-4-2..4, with
# space or dash) OR a real brand prefix (4x Visa, 5[1-5]x Mastercard, 3[47]x
# Amex, 6(011|5xx) Discover). A raw 13-16 digit number + Luhn is noise —
# not detected (1 in 9 sequences passes Luhn by chance).
_CARD_RE = re.compile(
    _NO_BOUNDARY_L
    + r"(?:"
    r"\d{4}[ -]\d{4}[ -]\d{4}[ -]\d{1,4}"
    r"|4\d{12}(?:\d{3})?"
    r"|5[1-5]\d{14}"
    r"|3[47]\d{13}"
    r"|6(?:011|5\d{2})\d{12}"
    r")"
    + _NO_BOUNDARY_R
)


def _luhn(digits: str) -> bool:
    """Validates a card number with the Luhn algorithm (digits only)."""
    digits = re.sub(r"\D", "", digits)
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:  # doubles alternating digits, right to left
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


class CardGuardrail(RegexGuardrail):
    """Redacts credit card numbers (grouped or brand-prefixed, Luhn-checked)."""

    name = "card"
    marker = "[CARD_HIDDEN]"
    patterns = (_CARD_RE,)
    validators = (
        lambda digits: 13 <= len(re.sub(r"\D", "", digits)) <= 16 and _luhn(digits),
    )


__all__ = ["EmailGuardrail", "CardGuardrail", "GuardrailContext", "GuardrailResult"]