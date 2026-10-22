"""minimal-chat domain — the DomainSpec Semente assembles into the app.

Besides the example tool, this domain declares input guardrails: they run on
every user input (pipeline, channel doors, persistence) and redact sensitive
spans or block the turn. See docs: Guardrails.
"""

import re

from semente import tool
from semente.domain import DomainSpec
from semente.guardrails import (
    EmailGuardrail,
    GuardrailContext,
    GuardrailResult,
    RegexGuardrail,
)


@tool(description="Echo the given message back to the user.")
def echo(message: str) -> str:
    """Return the message unchanged — an example tool to replace."""
    return f"Echo: {message}"


class PhoneGuardrail(RegexGuardrail):
    """Redacts phone numbers — an example of a custom regex guard."""

    name = "phone"
    marker = "[PHONE_HIDDEN]"
    patterns = (
        # Brazilian-style formatting: area code + 4 or 5 digits + last 4.
        re.compile(r"(?<!\d)\d{2}[ -]\d{4,5}[ -]?\d{4}(?!\d)"),
    )


_CREDENTIALS_RE = re.compile(r"(?i)\b(password|passwd|senha)\b")


class CredentialsBlocker(RegexGuardrail):
    """Demonstrates the blocking path: refuse messages with credentials.

    Unlike the redaction guards above, this one returns ``blocked=True`` —
    the harness answers with ``response`` and the agent never runs the turn.
    """

    name = "credentials"

    def redact(self, context: GuardrailContext) -> GuardrailResult:
        if _CREDENTIALS_RE.search(context.text or ""):
            return GuardrailResult(
                text=context.text,
                blocked=True,
                response=(
                    "For security, I can't process messages containing "
                    "credentials (passwords). Please rephrase without them."
                ),
            )
        return GuardrailResult(text=context.text)


domain_spec = DomainSpec(
    name="minimal-chat",
    tools=[echo],
    guardrails=[PhoneGuardrail(), EmailGuardrail(), CredentialsBlocker()],
)