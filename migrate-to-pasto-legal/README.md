# Migrate to Pasto Legal

Semente was extracted from [Pasto Legal](https://github.com/lapig-ufg/pasto-legal).
When the framework grew its **pluggable input-guardrail interface**
(`semente/guardrails/`), the domain-neutral parts (the protocol, the chain,
universal guards like e-mail and credit card) stayed in Semente — while the
Brazil-specific PII detectors moved here, into their home project.

## What moved and why

| Was (Semente ≤ 0.3) | Now (Semente ≥ 0.4) |
|---|---|
| `semente/guardrails/pii_gate.py` — CPF, CNPJ, RG, CAR known-scope, pt-BR intent layer | **`migrate-to-pasto-legal/guardrails/brazil_pii.py`**, adapted to the new interface as **`BrazilPiIGuardrail`** |
| `semente/guardrails/pii_gate.py` — e-mail, credit card | Stays in the framework, opt-in: `from semente.guardrails import EmailGuardrail, CardGuardrail` |
| `tools/feedback_tools.py` — CPF/CNPJ/CAR masking | Done by the guardrail chain (tool now masks only latitude/longitude pairs locally) |
| `features.pii_guardrail` in `semente.yaml` | Renamed **`features.guardrails`** (the old key still loads with a deprecation warning) |

The guards are **opt-in** now: a guard runs only when the app declares it in
`DomainSpec.guardrails`. Pasto Legal must declare its guardrail(s) explicitly
— which is the point: the framework no longer hardcodes Brazil/LGPD rules.

## How to implement it in Pasto Legal

### 1. Upgrade Semente

Use a Semente release containing the guardrail interface (v0.4+):

```bash
uv pip install -U semente-agents
```

### 2. Copy the guardrail into the domain

```bash
# in the semente repo:
cp migrate-to-pasto-legal/guardrails/brazil_pii.py  <pasto-legal>/domain/guardrails/brazil_pii.py
touch <pasto-legal>/domain/guardrails/__init__.py   # make it a package
```

The file has **no framework-internal imports** — it only depends on the
public contract:

```python
from semente.guardrails import GuardrailContext, GuardrailResult, RegexGuardrail
```

While you're in the file, extend `_KNOWN_SCOPE` with any additional long
identifiers Pasto Legal owns (long identifiers can randomly validate as
documents — e.g. 1 in ~3,000 CAR codes — so they are excised before the
scan; the same reasoning applies to your own long IDs).

### 3. Declare the guardrails in the domain spec

```python
# domain/__init__.py
from semente.domain import DomainSpec
from semente.guardrails import EmailGuardrail, CardGuardrail
from domain.guardrails.brazil_pii import BrazilPiIGuardrail  # or relative: .guardrails.brazil_pii

domain_spec = DomainSpec(
    name="Pasto Legal",
    tools=get_tools,
    guardrails=[
        BrazilPiIGuardrail(),   # CPF / CNPJ / RG / pt-BR intent layer / CAR protection
        EmailGuardrail(),
        CardGuardrail(),        # keep card Luhn coverage (the legacy API kept it)
    ],
)
```

> The universal guards listed here (e-mail, card) are what the old
> `pii_gate` also covered — without them, that part of the old behavior is
> lost. Declare the list, don't assume defaults.

Once declared, the framework routes everything through the chain:

| Stage | Detail |
|---|---|
| Pipeline | redacts (or **blocks**) the consolidated turn text; a `blocked` guard answers with its `response` and the run skips the agent |
| Media | image descriptions / audio transcriptions are redacted **before** they are persisted in the run history |
| WhatsApp door | `MessageContent.__post_init__` redacts before raw text reaches the router's logs, Valkey, or the DB |
| Streamlit | **displays the full raw input on purpose** (development UI) — `run()` protects everything downstream |
| Persistence | DPO/SFT feedback rows are sanitized field-by-field (`sanitize_json`) |
| Logs | every removal is logged with **types only, never values** (`guardrails[pipeline]: removed (CPF, email)`) |

### 4. Update the manifest

```yaml
# semente.yaml
features:
  guardrails: true   # default; only rename if your manifest had pii_guardrail
```

### 5. Port the tests

`tests_brazil_pii.py` in this folder is the original
`tests/guardrails/test_pii_gate.py` suite, updated to the new interface —
fully deterministic (no LLM/network). To bring it into Pasto Legal:

1. Copy it to Pasto Legal's test suite (e.g. `tests/test_brazil_pii.py`).
2. Edit the two module-loading lines at the top to point at the *copied*
   module (the loader uses a file path — the folder name here is not a valid
   Python package identifier):

```python
_MODULE_PATH = pathlib.Path(__file__).resolve().parents[1] / "domain/guardrails/brazil_pii.py"
```

3. `BrazilPiIGuardrail` redacts the same spans as `redact_pii`; the
   e-mail/card cases now live in the framework builtins (the suite covers
   their composition with the Brazil guard).

### 6. Blocking behavior (optional, new)

The interface supports refusing the whole turn with a user-facing reply —
the Brazil guards only redact, so nothing changes for them. If Pasto Legal
ever wants a hard refusal (e.g. policy violations), implement a guard whose
`redact` returns `GuardrailResult(text=..., blocked=True, response="...")`
and the harness short-circuits the turn (agent never runs). See
`examples/minimal-chat/domain/__init__.py` (`CredentialsBlocker`) in the
Semente repo for a reference implementation.

## Verify

Smoke-test the guards without any LLM:

```bash
python -c "
from semente.guardrails import GuardrailChain, GuardrailContext
import domain
c = GuardrailChain(domain.domain_spec.guardrails)
print(c.redact(GuardrailContext(text='my cpf is 710.768.971-18')))
"
# expect: GuardrailResult(text='my cpf is [CPF_HIDDEN]', removed=['CPF'], ...)
```

Then run the ported suite and the app:

```bash
python -m pytest tests/test_brazil_pii.py
semente status          # features: guardrails ... on
```

Finally, live: send a message containing `CPF 123.456.789-09` — the terminal
logs `guardrails[pipeline]: removed (CPF)` and the agent's context contains
`[CPF_HIDDEN]`, never the number.