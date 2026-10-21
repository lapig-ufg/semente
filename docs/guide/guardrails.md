# Guardrails

Input guardrails inspect the raw user input of a turn and either **redact**
sensitive data (keeping the rest of the request) or **block** the turn with a
user-facing reply. They are **pluggable and opt-in**: an app declares its
guards in the `DomainSpec`, and the framework runs the same chain everywhere
input can leak — the pipeline, the channels, media-derived text, and the
persistence layer.

> **Privacy is declaration-driven.** An app with no `guardrails` in its
> `DomainSpec` redacts nothing. Declare only what fits your jurisdiction and
> domain — the framework ships universal guards (e-mail, credit card) and
> stays out of country/document specifics.

## Declaring guardrails

```python
from semente import EmailGuardrail
from semente.domain import DomainSpec

domain_spec = DomainSpec(
    name="My App",
    tools=[...],
    guardrails=[EmailGuardrail(), CardGuardrail()],
)
```

The chain is composed once by the harness (`get_harness`) and reused at:

| Stage | What the chain does |
|---|---|
| Pipeline (`source="pipeline"`) | Redacts the consolidated turn text (including media transcriptions merged later by `_input_preprocessing` — those run first, `source="media"`, so nothing raw is persisted) |
| Channel doors (`source="channel"`) | WhatsApp `MessageContent` and the Streamlit webapp redact/tone down logs before the text reaches cache, database, or the chat display |
| Persistence | DPO/SFT feedback rows are sanitized field-by-field (`sanitize_json`) |
| Logs | Every guard can provide a `mask()` — log lines keep the shape, drop the values |

The manifest feature toggle `guardrails` (default `true`) turns the whole
chain off if you ever need it (`features.guardrails: false`); the legacy key
`pii_guardrail` is still accepted with a deprecation warning.

## Writing your own

The framework is deliberately flat — no plugin registry, no interface
hierarchy. Implement the two-attribute protocol (or subclass `RegexGuardrail`
for the common regex case):

### Regex guardrails (subclass)

```python
import re
from semente.guardrails import RegexGuardrail

class PhoneGuardrail(RegexGuardrail):
    name = "phone"                    # log-safe identifier
    marker = "[PHONE_HIDDEN]"         # written into the text
    patterns = (
        re.compile(r"(?<!\d)\d{2}[ -]\d{4,5}[ -]?\d{4}(?!\d)"),
    )
    # optional, aligned with patterns: validators accept the match text,
    # returning False keeps it (check-digit style filtering)
```

`redact` replaces every validated match with the marker and reports
`removed: ["phone"]`; `mask` over-matches for logs without validators.

### Blocking guards

Return a `blocked` result to refuse the turn entirely — the agent never
runs and the user receives `response`:

```python
from semente.guardrails import GuardrailContext, GuardrailResult, RegexGuardrail

class SecretsGuardrail(RegexGuardrail):
    name = "secrets"
    marker = "[X]"

    def redact(self, context: GuardrailContext) -> GuardrailResult:
        match = _SECRET_RE.search(context.text)
        if match:
            return GuardrailResult(
                text=context.text,
                blocked=True,
                response="For security reasons, I can't process messages with credentials.",
            )
        return super().redact(context)
```

### Functional guards (duck-typed)

Any object with `name` and `redact(context) -> GuardrailResult` satisfies the
protocol — no inheritance required.

## Built-in guardrails

Guard | Import | Behavior
---|---|---
`EmailGuardrail` | `from semente.guardrails import EmailGuardrail` | Redacts e-mail addresses (format-based)
`CardGuardrail` | `from semente.guardrails import CardGuardrail` | Redacts card numbers (grouped or brand-prefixed, Luhn-validated); bare 13–16 digit numbers are intentionally ignored — 1 in 9 passes Luhn by chance

## GuardrailContext and GuardrailResult

```python
from semente.guardrails import GuardrailContext, GuardrailResult

@dataclass
class GuardrailContext:
    text: str                   # rewritten by previous guards in the chain
    session_state: dict | None
    user_id: str | None
    source: str                 # "channel" | "media" | "pipeline" | "tool"

@dataclass
class GuardrailResult:
    text: str                   # hand this to the next guard/stage
    removed: list[str]          # types only — logs never see values
    blocked: bool
    response: str | None        # the user-facing refusal when blocked
```

## The Brazil/LGPD set

The original framework guards (CPF, CNPJ, RG, CAR protection, pt-BR intent
layer) were **extracted from Semente** into their home project — see
`migrate-to-pasto-legal/` and
[Pasto Legal](/showcase/pasto-legal) for how a domain re-introduces
country-specific detectors with this interface.

## Debugging

The guardrail chain is visible in the Streamlit debug panel's session state,
and every removal is logged with **types only**
(`guardrails: data removed (CPF, email)`), never values.