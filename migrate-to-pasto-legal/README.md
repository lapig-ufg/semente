# Migrate to Pasto Legal

Semente was extracted from [Pasto Legal](https://github.com/lapig-ufg/pasto-legal).
When the framework grew its **pluggable input-guardrail interface**
(`semente/guardrails/`), the domain-neutral parts (the protocol, the chain,
universal guards like e-mail and credit card) stayed in Semente — while the
Brazil-specific PII detectors moved here, into their home project.

## What moved and why

| Was | Now |
|---|---|
| `semente/guardrails/pii_gate.py` (CPF, CNPJ, RG, CAR known-scope, pt-BR intent layer) | `migrate-to-pasto-legal/guardrails/brazil_pii.py` — adapted to the new interface as **`BrazilPiIGuardrail`** |
| `semente/guardrails/pii_gate.py` (e-mail, credit card) | Stays in the framework as `from semente.guardrails import EmailGuardrail, CardGuardrail` |
| `tools/feedback_tools.py` CPF/CNPJ/CAR masking | Done by the guardrail chain; only lat/long masking remains in the tool |
| `features.pii_guardrail` in `semente.yaml` | Renamed `features.guardrails` (`pii_guardrail` still accepted as a deprecated alias) |

The guards are **opt-in now**: a guard runs only when the app declares it.
Pasto Legal must declare its guardrail(s) explicitly — which is the point:
the framework no longer hardcodes Brazil/LGPD rules.

## How to implement it in Pasto Legal

### 1. Upgrade Semente

Use the Semente release containing the guardrail interface (v0.4+):

```bash
uv pip install -U semente-agents
```

### 2. Copy the guardrail into the domain

Copy `guardrails/brazil_pii.py` into Pasto Legal's `domain/` package
(e.g. `domain/guardrails/brazil_pii.py`). It has **no framework-internal
imports** — it only depends on the public contract:

```python
from semente.guardrails import GuardrailContext, GuardrailResult, RegexGuardrail
```

Extend `_KNOWN_SCOPE` there with any additional long identifiers Pasto Legal
owns (long identifiers can randomly validate as documents, so they are
removed before the scan).

### 3. Declare the guardrails in the domain spec

```python
# domain/__init__.py
from semente import EmailGuardrail
from semente.domain import DomainSpec
from .guardrails.brazil_pii import BrazilPiIGuardrail

domain_spec = DomainSpec(
    name="Pasto Legal",
    tools=get_tools,
    guardrails=[
        BrazilPiIGuardrail(),   # CPF / CNPJ / RG / intent layer / CAR protection
        EmailGuardrail(),
        CardGuardrail(),        # from semente.guardrails; keep card Luhn coverage
    ],
)
```

Once this is set, the framework routes **everything** through the chain:

- the consolidated turn text (pipeline stage),
- image descriptions and audio transcriptions before they are persisted,
- the WhatsApp door (`MessageContent`) and the Streamlit door,
- DPO/SFT persistence (`sanitize_json`),
- log masking (`mask`).

### 4. Update the manifest

```yaml
# semente.yaml
features:
  guardrails: true   # pii_guardrail still works but logs a deprecation warning
```

### 5. Port your tests

`tests_brazil_pii.py` in this folder is the original
`tests/guardrails/test_pii_gate.py` suite, updated to the new interface —
copy it into Pasto Legal's test suite. It is fully deterministic (no
LLM/network).

### 6. Blocking behavior (optional, new)

The interface supports refusing the whole turn with a user-facing reply.
The Brazil guards only redact, so no change is needed; if Pasto Legal ever
wants, e.g., a hard refusal for policy violations, implement a guard whose
`redact` returns `GuardrailResult(text=..., blocked=True, response="...")`
and the harness short-circuits the turn (agent never runs).

## Verify

```bash
python -m pytest tests_brazil_pii.py
# and in the app:
semente status        # features: guardrails ... on
```

Then manually: send a message with `CPF 123.456.789-09` — the agent's
context must contain `[CPF_HIDDEN]`, never the number.