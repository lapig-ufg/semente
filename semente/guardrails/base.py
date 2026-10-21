"""The input-guardrail contract — how apps customize input safety.

A guardrail is a small object that inspects the user text of a turn and
returns a possibly-rewritten version (redaction) and/or a refusal (blocking).
Semente chains the guards the domain declares, in list order, and routes the
same chain through every touchpoint: the pipeline stage, the channel doors
(Streamlit/WhatsApp), media-derived text, and the persistence sanitization.

Writing one::

    from semente.guardrails import RegexGuardrail

    class PhoneGuardrail(RegexGuardrail):
        name = "phone"
        marker = "[PHONE_HIDDEN]"
        patterns = (re.compile(r"\\+?\\d[\\d\\- ]{8,}\\d"),)

    domain_spec = DomainSpec(..., guardrails=[EmailGuardrail(), PhoneGuardrail()])

The chain is composed once by the harness (``get_harness``) and published as
the module-level *active chain* (:func:`set_active_chain` /
:func:`active_chain`), so channels and persistence reuse exactly the same
guards — mirrors the ``set_engine``/``set_prompts_dir`` singletons.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Optional, Protocol, runtime_checkable


@dataclass
class GuardrailContext:
    """Everything a guard may need about the input being inspected.

    Attributes:
        text: The text as rewritten by the previous guards in the chain.
        session_state: The session state (read-only usage recommended).
        user_id: Persistence coordinates, when known.
        source: Where in the pipeline the guard runs — ``"channel"``
            (door redaction), ``"media"`` (transcription/description),
            ``"pipeline"`` (the consolidated turn text), or ``"tool"``.
    """

    text: str
    session_state: dict | None = None
    user_id: str | None = None
    source: str = "pipeline"


@dataclass
class GuardrailResult:
    """What one guard (or the whole chain) decided about a text.

    Attributes:
        text: The (possibly redacted) text to hand to the next guard/stage.
        removed: Types removed — for logs only, never the values.
        blocked: True refuses the whole turn; ``response`` is the reply.
        response: User-facing reply when ``blocked`` (agent never runs).
    """

    text: str
    removed: list[str] = field(default_factory=list)
    blocked: bool = False
    response: Optional[str] = None


@runtime_checkable
class InputGuardrail(Protocol):
    """The contract every guard implements.

    ``redact`` is required; ``mask`` (for safe logs) is optional — when a
    guard does not implement it, the chain falls back to the guard's
    redaction behavior.
    """

    name: str

    def redact(self, context: GuardrailContext) -> GuardrailResult: ...


class RegexGuardrail:
    """Base class for regex-driven guards with optional check-digit validation.

    Subclasses set class attributes — no method overrides needed:

    - ``name``: log-safe identifier (e.g. ``"email"``).
    - ``marker``: replacement written into the text (e.g. ``[EMAIL_HIDDEN]``).
    - ``patterns``: one or more compiled regexes describing the sensitive span.
    - ``validators``: optional per-pattern callables (receives the match
      text, returns False to keep it). Use for check-digit documents; leave
      ``None`` when the format itself is the evidence (email, RG).
    """

    name: str = "regex"
    marker: str = "[HIDDEN]"
    patterns: tuple[re.Pattern, ...] = ()
    validators: Optional[tuple[Callable[[str], bool], ...]] = None
    # Log masking replaces matches with this marker (no validators — a log
    # mask may over-match, but must never under-report).
    mask_marker: str = "[hidden]"

    def _findings(self, text: str) -> list[tuple[int, int]]:
        """Spans (merged, non-overlapping) of the matches the guard keeps."""
        spans: list[tuple[int, int]] = []
        for i, rx in enumerate(self.patterns):
            validator = self.validators[i] if self.validators else None
            for match in rx.finditer(text):
                if validator is not None and not validator(match.group(0)):
                    continue
                spans.append(match.span())
        if not spans:
            return []
        spans.sort()
        merged = [spans[0]]
        for start, end in spans[1:]:
            last_start, last_end = merged[-1]
            if start < last_end:
                merged[-1] = (last_start, max(last_end, end))
            else:
                merged.append((start, end))
        return merged

    def redact(self, context: GuardrailContext) -> GuardrailResult:
        text = context.text
        spans = self._findings(text)
        if not spans:
            return GuardrailResult(text=text)
        removed = self.name
        for start, end in reversed(spans):
            text = text[:start] + self.marker + text[end:]
        return GuardrailResult(text=text, removed=[removed])

    def mask(self, text: str) -> str:
        spans = self._findings(text)
        if not spans:
            return text
        for start, end in reversed(spans):
            text = text[:start] + self.mask_marker + text[end:]
        return text


class GuardrailChain:
    """The domain's guards, run in list order as one composite guard.

    ``redact`` threads the text through every guard, aggregating the removed
    types; the first ``blocked`` result wins and is reported as the chain's
    decision. ``mask`` threads the log-masking in the same order (missing
    ``mask`` implementations fall back to replacing matches with the guard's
    redact behavior — over-redacting a log is acceptable, leaking is not).
    """

    def __init__(self, guardrails: list | None = None):
        self.guardrails = [
            g() if isinstance(g, type) else g for g in (guardrails or [])
        ]

    @property
    def enabled(self) -> bool:
        return bool(self.guardrails)

    # -- redaction --------------------------------------------------------

    def redact(self, context: GuardrailContext) -> GuardrailResult:
        if not self.enabled:
            return GuardrailResult(text=context.text)
        text, removed, blocked_result = context.text, [], None
        for guard in self.guardrails:
            result = guard.redact(
                GuardrailContext(
                    text=text,
                    session_state=context.session_state,
                    user_id=context.user_id,
                    source=context.source,
                )
            )
            text = result.text
            removed.extend(result.removed)
            if result.blocked and blocked_result is None:
                blocked_result = result
        if blocked_result is not None:
            return GuardrailResult(
                text=text,
                removed=removed,
                blocked=True,
                response=blocked_result.response,
            )
        return GuardrailResult(text=text, removed=removed)

    def redact_text(self, text: str) -> str:
        """Redaction-only convenience (e.g. media-derived text)."""
        return self.redact(GuardrailContext(text=text or "")).text

    # -- masking (for safe logs) ------------------------------------------

    def mask(self, text: str) -> str:
        if not self.enabled:
            return text
        for guard in self.guardrails:
            mask = getattr(guard, "mask", None)
            if callable(mask):
                text = mask(text or "")
            else:
                result = guard.redact(GuardrailContext(text=text or ""))
                text = result.text
        return text

    # -- persistence -------------------------------------------------------

    def sanitize_json(self, data):
        """Recursively sanitize string values of JSON-like structures."""
        if isinstance(data, dict):
            return {key: self.sanitize_json(value) for key, value in data.items()}
        if isinstance(data, list):
            return [self.sanitize_json(item) for item in data]
        if isinstance(data, str):
            return self.redact_text(data)
        return data


# ---------------------------------------------------------------------------
# The active chain — a module-level singleton, like config/set_engine.
# ---------------------------------------------------------------------------

_active_chain: Optional[GuardrailChain] = None


def set_active_chain(chain: GuardrailChain | None) -> None:
    """Publish the app's chain (called once by ``get_harness``)."""
    global _active_chain
    _active_chain = chain


def active_chain() -> GuardrailChain | None:
    """The published chain, or ``None`` before ``get_harness`` ran."""
    return _active_chain


def redact_text(text: str) -> str:
    """Module-level redaction through the active chain (identity when none)."""
    chain = _active_chain
    if chain is None or not chain.enabled:
        return text
    return chain.redact_text(text)


def mask_text(text: str) -> str:
    """Module-level log masking through the active chain (identity when none)."""
    chain = _active_chain
    if chain is None or not chain.enabled:
        return text or ""
    return chain.mask(text)


def sanitize_json(data):
    """Module-level JSON sanitization through the active chain (identity)."""
    chain = _active_chain
    if chain is None or not chain.enabled:
        return data
    return chain.sanitize_json(data)