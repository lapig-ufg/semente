# PASTO_LEGAL_IMPORTS.md — pending changes to import from pasto-legal

Sync reference: semente commit
[`df820ff`](../../pasto-legal) — "Fix calculator schema: resolve PEP 563 string
annotations to real types" (**2026-09-16 22:20:25 -0300**). Everything on
pasto-legal `develop` from that date onwards must be evaluated for import.

Range: 4 direct commits + 2 merged PRs, tip fix last
(`git log --since="2026-09-16 22:20:25" --reverse` in pasto-legal):

```
ebcedb4  2026-09-17  fix: stop echoing user media back on WhatsApp replies
39e2267  2026-09-18  fix: forward geo files to agents and shrink paddock labels
34a002e  2026-09-18  update: Image ingest
5e61b33  2026-09-22  Merge PR #159 (feat/148-onboarding-perfil-usuario)
d534390  2026-09-22  Merge PR #157 (feature/147-session-state-migration)
0816be3  2026-09-24  fix: alinha o onboarding do welcoming agent ao portão do workflow
```

Items 1–6 cover that develop range and are DONE/N/A. **Item 7** was added
afterwards (2026-09-28): pasto-legal's develop had not moved, so the next
import was chosen from the strongest **unmerged** branch —
`fix/156-pii-falso-positivo-e-redacao`. If develop moves before Item 7 is
executed, re-evaluate: new develop commits take priority over branch tips.

Legend per item: **status** (`TODO` / `DONE` / `N/A`), source commit(s), files,
what changes, target path in semente, and adaptation notes. Check the box as
each item is completed.

---

## Item 1 — DONE — Media echo filter on the WhatsApp router

**Source:** `ebcedb4` (2026-09-17)

**Problem:** the workflow engines seed the run output's media lists
(`images/videos/audio/files`) with the same instances passed to `run()`, so the
WhatsApp router re-sends the user's own image/audio/document back to them. The
input step also attaches converted GeoJSON files (`format="geojson"`) to its
step output, and those internal artifacts would leak out as documents.

**pasto-legal files:**
- `app/interfaces/whatsapp/helpers.py` — adds `filter_generated_media(response, input_media)`:
  keeps only media not present in the run input (identity comparison by
  `id(item)`) and drops items with `format == "geojson"`.
- `app/interfaces/whatsapp/router.py` — in the send-out loop, replaces
  `items = getattr(response, attr, None)` with
  `items = filter_generated_media(response, run_kwargs).get(attr)`.
- `tests/interfaces/test_whatsapp_media_filter.py` — 9 tests (input echo,
  mixed input/generated, geojson artifacts, edge cases).

**Semente target:**
- [x] Port `filter_generated_media` into `semente/interfaces/whatsapp/helpers.py`.
- [x] `semente/interfaces/whatsapp/router.py:370` — use the filter in the media
  send-out loop (the same buggy `getattr(response, attr, None)` pattern is present).
- [x] Port the test file (adapt to the test layout — see notes).

**Adaptation notes:**
- The `id(item)` identity check is valid for the **agno backend** (agno's
  `WorkflowRunOutput` echoes the run input). The ADK/bare backends rebuild media
  objects at the boundary (`to_engine_media`), so for those the geojson-artifact
  rule is what applies; the test doubles should cover both shapes.
- Do **not** port pasto-legal's `tests/interfaces/conftest.py` (Valkey env
  shim) — semente's router imports lazily (`_get_valkey_client`) and needs no env
  vars at import time.
- Semente's equivalent output media lives on `StepOutput`
  (`semente/core/orchestrator.py:43-46`); the filter signature stays
  engine-agnostic via `getattr`, so it ports as-is.
- **Done (semente adaptation):** tests use semente-native media types
  (`semente.tools.types.Image/Video/Audio/File`) and `StepOutput` as the
  response stand-in instead of agno's `WorkflowRunOutput` — engine-neutral,
  covering both the identity-echo shape (agno) and the rebuilt-media shape
  (geojson rule). `tests/interfaces/conftest.py` was NOT created (no Valkey
  shim needed; router resolves Valkey lazily).

---

## Item 2 — DONE — Pass user images to agents

**Source:** `34a002e` (2026-09-18), twin `d7b76b3` on `feat/geo-files`

**Change:** `step_factory._agent_executor_factory` now passes
`images=step_input.images` to `agent.run(...)`, so agents receive the images of
the current turn.

**Semente status:** already ported — `semente/core/step_factory.py:135`
(`images=step_input.images or None` inside `AgentInput`).

- [x] No action needed (verified in commit `ccb949b`).

---

## Item 3 — DONE — Forward converted GeoJSON files to agents

**Source:** `39e2267` (2026-09-18), part (a)

**Change:** in `step_factory._agent_executor_factory`, look up the Input Step
output via `step_input.get_step_output(step_name=INPUT_STEP_NAME)` instead of
"the last previous output" (which was the PII guardrail and carried no media),
and pass its converted files to the agent.

**Semente status:** already ported — `semente/core/step_factory.py:120-137`
(same lookup + debug log), `INPUT_STEP_NAME` in
`semente/steps/input_step.py:46`, text lookup fix in
`semente/core/step_factory.py:21`.

- [x] No action needed (verified in commit `ccb949b`).

---

## Item 4 — N/A — GEE paddock labels (domain-side)

**Source:** `39e2267` (2026-09-18), part (b)

**Change (pasto-legal `app/services/geospatial/gee.py`):**
- Paddock labels show only the number (`"Paddock_12"` → `"12"`):
  `number = text.rsplit("_", 1)[-1]`.
- Smaller font/border so the label fits inside small paddocks:
  `font_size = max(12, int(height * 0.022))` (was `max(16, int(height * 0.035))`)
  and `stroke_width=2` (was `3`).

**Semente status:** not applicable — `gee.py` is a Pasto Legal domain service;
semente only carries the domain-neutral `semente/services/geospatial/geojson_io.py`.

- [x] No action. **Note for domains:** if a semente domain grows a GEE overview
  image service, apply the exact changes above (recorded here for traceability).

---

## Item 5 — DONE — Onboarding profile: user persona behind the gate

**Source:** PR #159 (`5e61b33`, branch `feat/148-onboarding-perfil-usuario`,
merged 2026-09-22) + tip fix `0816be3` (2026-09-24), the final aligned state.

**What it does:** onboarding now covers the identification profile (name +
role) in addition to the terms acceptance. The persona persists in a
`user_profile` table, and the gate + welcoming agent share a single
completeness rule so they can never disagree about whether the user is done.

### 5.1 Database model

- [x] Add to `semente/database/models.py`: `UserProfile` (`user_id` PK/index,
  `name`, `role` columns) as in pasto-legal `app/database/models.py`
  (introduced by `339c75f`, present on develop).

### 5.2 Persona persistence in tools

- [x] `semente/tools/persona_tools.py`: on `update_persona_name` /
  `update_persona_role`, persist the value to `user_profile` via a
  `_persistir_perfil(user_id, **campos)` helper (create row if missing; each
  tool writes only its own field so nothing the other wrote is erased).
  Get `user_id` from the run context or `session_state.get("user_id")`.

**Adaptation:** semente tools are native `@tool` with
`semente.context.Context` (not agno `RunContext`); resolve the context the same
way `steps/feedback/persona.py` does.

### 5.3 Shared completeness rule

- [x] `semente/schemas/user_persona.py`: add
  ```python
  UNKNOWN_PERSONA_VALUES = {
      UserPersona.model_fields["name"].default,
      UserPersona.model_fields["role"].default,
  }

  def is_persona_field_informed(value) -> bool: ...
  def is_persona_complete(persona) -> bool: ...
  ```
  The `UserPersona` fields default to the sentinel string ("Ainda não
  conhecido"), so a schema-built persona looks informed but is not — both the
  gate and the agent must treat the sentinel as missing (see
  `semente/schemas/user_persona.py:22-29`).

### 5.4 Persona-aware onboarding gate

- [x] Extract `_needs_onboarding` from `semente/workflows/base_workflow.py:35`
  into a new `semente/workflows/onboarding_gate.py`, keeping it free of
  agent/workflow-composition imports (only db models, session factory, persona
  schema, workflow_state).
- [x] New logic (aligned to pasto-legal tip `0816be3`):
  1. Lazy-init `workflow_state` slot.
  2. `terms_accepted = bool(session_state.get("terms_accepted"))`.
  3. If terms accepted **and** `is_persona_complete(persona)` → `False`.
  4. DB lookups only for what is missing: terms (unchanged) and, when
     `not is_persona_complete(persona)`, the `UserProfile` row.
  5. Fill only the fields still missing/sentinel
      (`for field in ("name", "role"): if not is_persona_field_informed(persona.get(field)) ...`)
      — never `setdefault`, and never erase what the agent just wrote this session.
  6. Final decision: `return not is_persona_complete(session_state.get("user_persona") or {})`.
  - `base_workflow.py` then imports `_needs_onboarding` from the gate module
  (as `0816be3` did for `pasto_legal_workflow.py`).

### 5.5 Staged welcoming agent

- [x] `semente/agents/welcoming_agent.py`: restructure to one stage per prompt.
  - `OnboardingStatus` enum (`NOT_ACCEPTED_TERMS`, `NOT_INFORMED_PERSONA`,
    `COMPLETE`) + `_get_onboarding_status(session_state)` driven by
    `terms_accepted` and `is_persona_complete`.
  - **Dynamic toolset:** expose only the current stage's tools (TTS always;
    `accept_terms_and_conditions` during terms; `update_persona_name` /
    `update_persona_role` during persona).
  - **Stage instructions:** `_TERMS_INSTRUCTION` (existing text), and for the
    persona stage format `instructions_persona` with `{user_name}`/`{user_role}`
    filled from the session or the `persona_not_informed` fallback.
  - Complete users return `""` (the gate routes them away before the agent runs).
- [x] Prompt keys in `semente/configs/prompts/defaults/agents.yml`
  (`welcoming_agent`): add `instructions_persona` (name+role stage) and
  `persona_not_informed` ("Not informed yet").
- [x] `semente/build_welcoming_agent` uses
  `AgentSpec(tools=_get_tools, instructions=get_instructions)` with
  `Context`-typed callables; keep the lazy prompts / `tts_enabled` behavior.

### 5.6 Tests

- [x] Port `tests/workflows/test_onboarding_profile.py` (9 tests: 7 gate
  scenarios + the 3 added by `0816be3` — session sentinel, sentinel cured from
  DB, partial fill without erasing the session value).
- [x] Semente tests have no DB fixtures yet — create a SQLite-based fixture
  (mirroring pasto-legal's fixture in the same file) for
  `UserTermsAcceptance`/`UserProfile` and `SessionLocal`.

**Adaptation notes (done):**
- All prompt loading stays lazy inside `build_welcoming_agent` (semente sets
  the language dir at workflow-build time, not import time); the loaded
  texts are closed over by the `Context`-typed callables.
- TTS stays gated on `tts_enabled` (manifest `features.tts`) — semente
  specific; in pasto-legal `generate_speech` is always present.
- Tool imports (`onboarding_tools`, `persona_tools`) are deferred into the
  stage callables so importing the agent module never touches the DB/prompt
  stack early; pasto-legal imports them at module top.
- Tools keep semente's inline f-string returns (pasto-legal's
  `get_tool_result_text` needs a `results:` block in tools.yml that
  semente's default tools.yml does not define) — deviation recorded here.
- The tools-callable + instructions-callable `AgentSpec` shape was verified
  against all three backends (agno `_wrap_tools`, bare/ADK `_resolve_tools`
  with `StateContext`).
- Name/role are stored as declared (`nome.strip()`; no `.title()` /
  `.capitalize()`), and `update_persona_name` gained pasto-legal's validation
  (reject empty, >60 chars, digits).
- **Scope addition (user decision, from PR #159):** `PersonaUpdate` lost its
  `name`/`role` fields and `steps/feedback/persona.py` stopped applying them
  ("dedução não sobrescreve declaração" — declared identity only changes via
  the explicit tools); the persona-manager step also gained the
  malformed-`user_mood` guard (discard + `log_error` instead of raising).
  The latent `__str__`-at-module-level bug in semente's `UserPersona` was
  fixed in passing (pasto-legal fixed it in the same PR).

---

## Item 6 — DONE — Session-state migration (wire into the gate)

**Source:** PR #157 (`d534390`, branch `feature/147-session-state-migration`,
merged 2026-09-22)

**Important caveat:** in pasto-legal's final state, `0816be3` deleted the call
site of `migrate_session_state` (the inline gate copy it rewrote), so the
service is currently dead code there. Decision for semente: **port it wired** —
restore the invocation at the top of the onboarding gate so old sessions get
upgraded.

- [x] Create `semente/services/session_migration.py`: `CURRENT_SCHEMA_VERSION`,
  `migrate_v0_to_v1` (ensures `_legacy_data`, `all_properties`, `user_persona`
  keys — generic; adjust the ensured keys to semente's session contract, e.g.
  `user_persona`/`user_mood`), `MIGRATIONS` registry, `migrate_session_state(raw_state)`
  (deep-copy, reads `workflow_state.schema_version`, walks the registry,
  stamps the final version).
- [x] Add `schema_version: int = Field(default=1, ...)` to
  `semente/schemas/workflow_state.py`.
- [x] In the new `semente/workflows/onboarding_gate.py` (Item 5.4), call at the top:
  ```python
  migrated_state = migrate_session_state(session_state)
  session_state.clear()
  session_state.update(migrated_state)
  ```
- [x] Port the migration tests (pasto-legal `tests/ee_scripts/test_session_migration.py`)
  into `tests/services/test_session_migration.py`.

**Adaptation notes (done):** `migrate_v0_to_v1` ensures semente's session
contract — `_legacy_data`, `user_persona`, `user_mood` — dropping pasto-legal's
domain-specific `all_properties` key (per the checklist's own note to adjust
the ensured keys). A fourth test (`test_migrate_does_not_mutate_input`) covers
the deep-copy guarantee that the wired call site relies on.

---

## Item 7 — TODO — PII redaction instead of blocking + false-positive fixes (branch, not yet on develop)

**Source:** pasto-legal branch `origin/fix/156-pii-falso-positivo-e-redacao`
(3 commits, all dated 2026-09-10, **unmerged** into develop — evaluated and
chosen as the next import on 2026-09-28, after the develop range above was
fully synced). Commits, in order:

- `87ee19a` — "fix: PII gate deixa de bloquear coordenadas e codigos CAR"
- `8d9c10a` — "fix: guardrail de PII passa a cobrir audio e imagem"
- `5caa7dd` — "feat: redacao de dados pessoais no lugar de bloqueio" (tip)

**What it does:** the PII guardrail stops *rejecting* whole messages and
starts *redacting* only the sensitive datum (replaced by a marker like
`[CPF_OCULTO]`), so the user's other requests in the same message survive.
Plus: the detectors stop producing false positives on coordinates and CAR
codes (measured before: 21.6% of location pins and 0.8% of CAR codes were
blocked), and audio transcriptions / image descriptions are now covered by
the gate. The webhook log is masked.

**Why it matters for semente:** every touched file maps 1:1 to semente engine
modules — this is almost pure engine code, no Pasto Legal domain logic
(the CAR regex is the only domain-smelling piece; see adaptation notes).

### 7.1 Detector hardening + redaction in `semente/guardrails/pii_gate.py`

Source: `app/guardrails/pii_gate.py` (see
`git diff develop...origin/fix/156-pii-falso-positivo-e-redacao --
app/guardrails/pii_gate.py` in pasto-legal; the file is ~310 lines at the
branch tip — read it whole, not just the diff, the comments carry the
rationale).

- [ ] **Camada 0 — known-scope exclusion:** `_CAR_RE`
  (`\b[A-Z]{2}-\d{7}-[A-F0-9]{32}\b`, IGNORECASE) + `_ESCOPO_CONHECIDO` list
  + `remover_escopo_conhecido(text)` (substitutes **a space**, not the empty
  string, so surrounding digits don't fuse). `check_pii` calls it first.
  Rationale: check digits are a weak signal (~1/100 random 11/14-digit
  sequences validate; ~1/9 for Luhn), so any long identifier eventually
  contains a "valid" fragment. Removing the fragment before scanning beats
  hardening the regex.
- [ ] **Boundary guards:** `_NB_L`/`_NB_R` lookaround helpers; documents must
  be whole tokens, never fragments of a bigger number.
- [ ] **Strict formats, three shapes each (never half-and-half):**
  - `_CPF_RE`: `123.456.789-01` | `123 456 789 01` | 11 raw digits
  - `_CNPJ_RE`: `12.345.678/0001-90` | `12 345 678 0001 90` | 14 raw digits
  - `_CARTAO_RE`: visually grouped (`\d{4}[ -]\d{4}[ -]\d{4}[ -]\d{1,4}`) OR
    a real brand prefix (4x Visa, 5[1-5]x Mastercard, 3[47]x Amex,
    6(011|5xx) Discover). Bare 13-16-digit + Luhn is noise — no longer
    detected.
- [ ] **`redigir_pii(text) -> (texto_redigido, tipos_removidos)`** replaces
  `mensagem_bloqueio` as the primary primitive: finds spans (CAR spans are
  protected from redaction too), validates check digits per type (RG and
  e-mail have no validator — format is the evidence), replaces
  back-to-front with overlap discard, returns the cleaned text + sorted
  unique types. `_MARCADOR` map: CPF/CNPJ/cartão/RG/e-mail →
  `[X_OCULTO]`.
- [ ] Keep `check_pii`, `mascarar_pii` (now including Camada 0 +
  `_INTENCAO_RE`), and all `detecta_*` (they're used by tests and the
  detection layer). **Remove `mensagem_bloqueio`/`_AVISO_BASE`** — the
  blocking path is gone. Update the module docstring interface list.

### 7.2 Guardrail step redacts instead of blocking — `semente/steps/guardrails_step.py`

- [ ] Replace the executor: read
  `step_input.previous_step_content or step_input.get_input_as_string()`
  (NOT `get_input_as_string()` alone — it returns the ORIGINAL workflow
  input, which would leave audio transcription and image description
  unscanned; semente's `StepInput` has `previous_step_content` at
  `semente/core/orchestrator.py:41`), run `redigir_pii`, `log_info` the
  removed types only (never the values), return `StepOutput(content=limpo)`
  — no `stop=True`, no TTS warning path (the whole blocking branch and the
  `generate_speech` import go away).
- [ ] Update the module docstring (redaction semantics + why the
  transcription/description redaction lives in the input step instead —
  step outputs are persisted in `step_results`).

### 7.3 Redaction at the four entry doors

- [ ] **WhatsApp typed text —** `semente/interfaces/whatsapp/helpers.py`:
  `MessageContent` gains `pii_removida: list = field(default_factory=list)`
  and a `__post_init__` that runs `redigir_pii(self.text or "")` (redact
  HERE, not per-branch of `extract_message_content`, so the raw text never
  reaches logs, Valkey or the DB — holds for today's branches and any
  future ones).
- [ ] **WhatsApp webhook log —** in `extract_message_content`, wrap the raw
  payload log (`log_info(message)`) and the text branch log with
  `mascarar_pii(str(...))` — the log runs BEFORE redaction.
- [ ] **Audio transcription + image description —**
  `semente/steps/input_step.py`: wrap `turn.content` of both media agents
  with `redigir_pii(...)` before appending to `parts` (typed text arrives
  already redacted; the step output is persisted, so redacting only in the
  next step would leave a raw copy in the DB).
- [ ] **Streamlit typed text —** `semente/interfaces/streamlit/streamlit_webapp.py`:
  `user_query, _pii_removida = redigir_pii(user_query)` right after the
  input is read (same reason: the raw text is persisted into the run's
  `input` field).

### 7.4 Agent prompt rules — `semente/configs/prompts/defaults/agents.yml`

- [ ] Port the "# Personal Data" block from the branch's
  `app/configs/prompts/defaults/agents.yml` into `single_agent.instructions_default`:
  never confirm saving personal data; never repeat it back; don't claim
  removal unless a `[..._OCULTO]` marker is literally present (and then say
  so in ONE short first line, then fulfill the rest normally); phone
  numbers are NOT removed (WhatsApp number identifies the user) — do not
  comment on them. Adapt wording to semente's neutral voice (drop Pasto
  Legal/CAR-specific mentions like "the property's location and CAR code";
  keep the marker rule verbatim in spirit).

### 7.5 Tests — `tests/guardrails/test_pii_gate.py` (new dir)

- [ ] Port the branch's `tests/ee_scripts/test_pii_gate.py` (~39 tests) —
  read it whole from the branch tip
  (`git show origin/fix/156-pii-falso-positivo-e-redacao:tests/ee_scripts/test_pii_gate.py`).
  Keep: all `detecta_*` unit tests, RG format, intention layer, orchestrator,
  masking; the regression corpus (`NAO_DEVE_BLOQUEAR` incl. real coordinate
  pins and six real CAR false positives; `DEVE_BLOQUEAR` parametrized);
  boundary-guard tests (fragment-of-bigger-number, sentence-final period);
  the spaced-format tests; Camada 0 tests; the two statistical tests (5000
  random coordinate pins / 5000 random CAR codes, seeded RNG — false
  positives were probabilistic, so the regression tests must be too).
- [ ] Adapt import paths to `semente.guardrails.pii_gate`; drop
  `mensagem_bloqueio` references; add redaction-specific assertions if the
  branch file lacks them (marker text present, non-sensitive tail preserved,
  `tipos` returned correctly, multiple PII in one message all redacted).
- [ ] Semente has no `tests/guardrails/` yet — create it (no `__init__.py`,
  matching the existing test layout).

**Adaptation notes (read before porting):**
- **CAR regex is domain-flavored but engine-safe:** the CAR code
  (Cadastro Ambiental Rural) is a Pasto Legal concept, yet it is exactly the
  kind of long system identifier a semente domain handles. Port `_CAR_RE`
  as-is (a domain can extend `_ESCOPO_CONHECIDO` with its own identifiers —
  keep the list a module-level extension point).
- **`redigir_pii` vs. `check_pii`:** the redaction primitive validates check
  digits per-match; `check_pii` stays for detection semantics (intent layer
  included). The guardrail step uses ONLY `redigir_pii` — a "cpf" mentioned
  with a redactable invalid number gets redacted by the regex shapes or
  caught by intent in `check_pii`, but the step no longer blocks either way.
- **`mascarar_pii` stays permissive on purpose** (over-masking in logs is
  cheap, under-masking is a leak) — its test asserts that.
- The TTS warning path in semente's guardrail step dies with blocking; the
  `[..._OCULTO]` marker + prompt rules replace the user-facing notice.
- Semente's `input_step` also appends converted GeoJSON file labels — those
  carry no user PII, leave them alone.
- The Streamlit demo text ("Minhas coordenadas são …") in the webapp is NOT
  PII and must survive redaction (it is in the corpus already).

---

## Suggested order

Items 1–6 are complete (see per-item notes). The remaining item:

1. [ ] Item 7 (PII redaction + false-positive fixes) — the chosen next
   import, from the unmerged branch `fix/156-pii-falso-positivo-e-redacao`.

## Verification

- [x] `pytest tests/` (green — 78 passed, incl. the new gate / migration /
  media-filter tests).
- [x] `python -c "import semente.workflows.base_workflow"` sanity import
  (requires an API key env var, as before — the test conftest provides a
  dummy one; the requirement is pre-existing, verified via git stash).
- [ ] Manual smoke with the Toy App (`examples/echo_domain/`): onboarding asks
  terms → name → role in stages; `/new` on an old session state does not crash
  (migration path); WhatsApp reply no longer echoes user media (if testing item 1).
- After Item 7: `pytest tests/` including the new
  `tests/guardrails/test_pii_gate.py`; manual smoke — send a message with a
  valid CPF plus a normal request (e.g. "meu cpf é 710.768.971-18, qual a
  versão do sistema?") and confirm BOTH happen: the marker `[CPF_OCULTO]`
  reaches the agent and the agent answers the request, warning in one line
  about the removed data; send a location/coordinate pin and confirm nothing
  is blocked.