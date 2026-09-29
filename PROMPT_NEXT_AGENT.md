# PROMPT_NEXT_AGENT.md — handoff prompt (paste this to the next agent)

Copy everything below the line into the new session.

---

## Task: import the PII redaction overhaul from pasto-legal into semente (Item 7)

### Context

**Semente** (`/home/tiago/Documents/Github/semente`, current working repo) is a
multi-agent AI chat framework extracted from **Pasto Legal**
(`/home/tiago/Documents/Github/pasto-legal`, read-only reference repo) — an AI
assistant that delivers satellite-based pasture diagnostics over WhatsApp.
Semente keeps the domain-neutral engine (multi-agent workflow, WhatsApp +
Streamlit channels, persona/feedback loop, PII guardrails, i18n prompts, TTS),
while domain logic (tools, knowledge, GEE services) lives in pasto-legal or in
semente "domains".

The previous sync waves (develop range after 2026-09-16) are COMPLETE — Items
1–6 in **`PASTO_LEGAL_IMPORTS.md`** (repo root) are DONE/N/A. Do not redo
them. Your job is **Item 7** at the end of that checklist, chosen from
pasto-legal's strongest unmerged branch:

- `origin/fix/156-pii-falso-positivo-e-redacao` (3 commits, tip `5caa7dd`):
  the PII guardrail switches from *blocking whole messages* to *redacting
  only the sensitive datum* (marker like `[CPF_OCULTO]`), the detectors stop
  false-positiving on coordinates and CAR codes (was: 21.6% of location pins,
  0.8% of CAR codes blocked), audio transcription and image description
  become covered, and the WhatsApp webhook log gets masked.

### Read first

1. `PASTO_LEGAL_IMPORTS.md` **Item 7** — the authoritative checklist for this
   task (sub-items 7.1–7.5, source files, adaptation notes, verification).
2. In pasto-legal, read the branch tip state of the touched files — read the
   FILES, not just diffs; the comments carry the rationale:
   ```
   git show origin/fix/156-pii-falso-positivo-e-redacao:app/guardrails/pii_gate.py
   git show origin/fix/156-pii-falso-positivo-e-redacao:app/steps/guardrails_step.py
   git show origin/fix/156-pii-falso-positivo-e-redacao:app/steps/input_step.py
   git show origin/fix/156-pii-falso-positivo-e-redacao:app/interfaces/whatsapp/helpers.py
   git show origin/fix/156-pii-falso-positivo-e-redacao:app/interfaces/streamlit/streamlit_webapp.py
   git show origin/fix/156-pii-falso-positivo-e-redacao:app/configs/prompts/defaults/agents.yml
   git show origin/fix/156-pii-falso-positivo-e-redacao:tests/ee_scripts/test_pii_gate.py
   ```

### What needs to be done (summary — details in the checklist item)

1. **7.1 `semente/guardrails/pii_gate.py`:** add Camada 0 (known-scope
   exclusion — `_CAR_RE` + `remover_escopo_conhecido`), boundary lookaround
   guards (`_NB_L`/`_NB_R`), strict three-shape regexes for CPF/CNPJ/cartão
   (punctuated | spaced | raw; cartão = visual grouping OR brand prefix), and
   `redigir_pii(text) -> (texto_redigido, tipos_removidos)`. Remove
   `mensagem_bloqueio`/`_AVISO_BASE`. Keep `check_pii`, `mascarar_pii`,
   `detecta_*`.
2. **7.2 `semente/steps/guardrails_step.py`:** redact instead of block —
   read `step_input.previous_step_content or step_input.get_input_as_string()`
   (NOT `get_input_as_string()` alone: it returns the ORIGINAL workflow input,
   leaving audio transcription and image description unscanned), run
   `redigir_pii`, `log_info` the removed types only, return
   `StepOutput(content=limpo)`. The blocking branch and the TTS warning path
   die entirely.
3. **7.3 Redaction at the four entry doors:** (a) WhatsApp
   `MessageContent.__post_init__` + `pii_removida` field
   (`semente/interfaces/whatsapp/helpers.py`); (b) mask the raw webhook
   payload/text logs with `mascarar_pii`; (c) wrap the media agents'
   `turn.content` with `redigir_pii` in `semente/steps/input_step.py`
   (transcription + description; their output is persisted, so redacting one
   step later would leave a raw copy in the DB); (d)
   `user_query, _pii_removida = redigir_pii(user_query)` in
   `semente/interfaces/streamlit/streamlit_webapp.py`.
4. **7.4 Prompt rules:** port the "# Personal Data" block into
   `semente/configs/prompts/defaults/agents.yml`
   (`single_agent.instructions_default`) — never confirm saving personal data,
   never repeat it, only acknowledge removal when a `[..._OCULTO]` marker is
   literally present (one short first line, then fulfill the rest), phones
   are not removed. Adapt to semente's neutral voice (drop Pasto Legal/CAR
   specifics).
5. **7.5 Tests:** port the ~39-test
   `tests/ee_scripts/test_pii_gate.py` into new
   `tests/guardrails/test_pii_gate.py` — including the regression corpus
   (`NAO_DEVE_BLOQUEAR` / `DEVE_BLOQUEAR`, six real CAR false positives) and
   the two seeded statistical tests (5000 coordinate pins / 5000 CAR codes —
   the false positive was probabilistic, so the regression test must be too).
   Adapt imports to `semente.guardrails.pii_gate`.

### Structural differences semente vs pasto-legal (respect these when porting)

- **Logging:** `semente.logging` (`log_info/log_error/...`), never agno's
  log utils. **Orchestrator:** hand-written `semente/core/orchestrator.py` —
  `StepInput` has both `previous_step_content` (line 41) and
  `get_input_as_string()` (line 49); steps chain via
  `step_input.previous_step_content = output.content` (line 176), so the
  guardrail step reading `previous_step_content` sees the input step's
  consolidated text.
- **Media agents** are backend-neutral agents run via
  `AgentInput`/`AgentTurn` (`turn = image_description_agent.run(AgentInput(...))`
  in `semente/steps/input_step.py`) — redact `turn.content`, not
  `response.content`.
- **Prompts:** semente's `configs/prompts/defaults/agents.yml` is the neutral
  English fallback merged under the app's localized file; keep the neutral
  voice. `single_agent.instructions_default` is the block to extend.
- **Path/prefix:** `app/...` → `semente/...`. **Tests:** no `__init__.py` in
  test dirs; `.venv` at the repo root has the dev environment (use
  `.venv/bin/pytest`); `tests/conftest.py` already provides dummy API keys.
- **Engine note:** the guardrail step runs inside the workflow regardless of
  the backend; nothing in Item 7 is engine-specific.

### Working rules

- Work through Item 7 sub-items top-to-bottom (7.1 → 7.5); after finishing,
  edit `PASTO_LEGAL_IMPORTS.md` to flip Item 7's status TODO → DONE, check
  its boxes, and record deviations in its adaptation notes so progress
  survives an interruption.
- Do not commit unless explicitly asked.
- Match semente's existing code style; keep code comments minimal (the source
  file's rationale comments in `pii_gate.py` are the exception — they explain
  non-obvious security invariants; port the load-bearing ones).
- Pasto-legal code is the source of truth for the *what*; semente's
  architecture dictates the *how*. When they conflict, adapt to semente and
  note the difference in the checklist item's adaptation notes.
- Read the branch tip state (commands above), not intermediate commits —
  the tip is the aligned final state.

### Verification (must pass before declaring done)

- `.venv/bin/pytest tests/` from the repo root — all green, including the
  new `tests/guardrails/test_pii_gate.py` and the pre-existing 78 tests.
- `.venv/bin/python -c "import semente.workflows.base_workflow"` (needs an
  API key env var — same pre-existing requirement as the suite conftest).
- Quick behavioral check (no LLM needed):
  ```
  .venv/bin/python -c "
  from semente.guardrails.pii_gate import redigir_pii
  print(redigir_pii('meu cpf é 710.768.971-18, qual a versão do sistema?'))
  print(redigir_pii('Lat: -5.935149162520979 Long: -52.50857591629029'))
  print(redigir_pii('GO-5212303-27057D4194F64CE3A498B90BFAC2E5F9'))
  "
  ```
  Expect: CPF replaced by `[CPF_OCULTO]` with the request intact; coordinate
  pin untouched; CAR untouched.
- Optional manual smoke with the Toy App (`examples/echo_domain/`): a
  message mixing a valid CPF and a real request → agent answers the request
  and mentions the removal in ONE first line; a location pin → nothing
  blocked.
- Finish by summarizing: what was completed, any deviations from the
  checklist, and anything left open with the reason.