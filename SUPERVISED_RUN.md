# SUPERVISED_RUN.md — the supervised run feature: design, decisions, and working log

**Status: implemented & tested (all decisions below are in the code).**

This file is the single record of the supervised run feature's decisions, so the
work can be resumed cold later. Append new decisions to the log at the end;
keep the body in sync with what ships.

---

## 1. What it is

A customizable, domain-owned guided supervised run that rides above the normal
assistant. The domain decides **how many steps, what each step teaches, when
to forward to the real assistant, and how a step is judged concluded**. The
framework owns the machinery: the offer, the message grading, the step
advancing, and the persistence of the final outcome.

Origin: the first attempt (never committed) hardcoded a 3-step, Pasto
Legal–specific flow inside `workflow_state.py`/`agents.yml` — the rework
generalized everything into the `get_supervised_run` seam.

## 2. The seam (what a domain writes)

```python
from semente.domain import DomainSpec, SupervisedRun, SupervisedRunStep

def get_supervised_run() -> SupervisedRun:
    return SupervisedRun(
        steps=[
            SupervisedRunStep(
                id="registration",            # labels the step (prompts, offer menu)
                lesson="…teaching…",           # what the step teaches, one chat-style message
                forward_condition="…",         # injected into the supervisor prompt (forward=true)
                complete_condition="…" | callable,  # str → checkpoint agent; callable → pipeline
            ),
            …  # any count: the supervised run is as short/long as this list
        ],
        offer=None,    # optional custom ask for the welcoming agent
        closing=None,  # optional final message after the last step
        abandon=None,  # optional reply when the user leaves early
    )

domain_spec = DomainSpec(name="My App", tools=..., get_supervised_run=get_supervised_run)
```

- `complete_condition` callable contract: `f(session_state, user_text, agent_reply) -> bool`.
  The live `session_state` is injected — the domain reads whatever its tools wrote.
- `title`/`right_path`/`done_when` (from an earlier iteration) were **removed** —
  `id` + `lesson` + the two conditions are the whole step.

## 3. Runtime flow

```
run() routing (_execute):
  onboarding needed ────────► welcoming agent (terms / persona / supervised run offer)
  supervised_run UNDECIDED ───────► welcoming agent (supervised_run-offer stage, set_supervised_run_choice)
  supervised run RUNNING ─────────► supervised run branch:
      user message ────────► SUPERVISOR (supervised_run_agent, yml tag `supervised_run_agent`)
                              SupervisedRunDecision { forward, content, abandon_supervised_run }
        forward=true ─────► normal agent answers (real work)
        forward=false ────► the lesson/coaching content is the reply; lesson marked delivered
        abandon=true ─────► supervised run closed (session COMPLETED + DB row)
      after a forward ─────► CHECKPOINT (semente.agents.supervised_run_agent, yml tag
                              `supervised_run_check_agent`):
          condition is str   → CompletionCheck { step_completed } judged from
                               <user_message> + <assistant_reply> (+ condition + history)
          condition callable → f(session_state, user_text, agent_reply), no LLM
        completed ──────────► advance: state index+1 (intro_sent=True — the announcement
                               delivered the next lesson) and APPEND the announcement:
                               congrats + next step's lesson (yml
                               `supervised_run_check_agent.completion_announcement`)
        last step completed ► close for good: COMPLETED + UserSupervisedRunProgress row,
                               announcement = SupervisedRun.closing or yml `closing_default`
  supervised_run DONE / no spec ──► normal path
```

- The supervisor decides **only** routing. It never judges completion (that
  was the first-attempt design; removed).
- A completed (announced) step is born **lesson-delivered** so the
  supervisor does not repeat it next turn.
- On a non-forwarded turn the supervisor delivers an undelivered lesson and
  marks it; forwards never touch the lesson flag.

## 4. State & persistence

- `workflow_state.supervised_run_state` (`semente/schemas/workflow_state.py`):
  `None` (offer unanswered) / `"0"`,`"1"`,… (0-based step index) / `"COMPLETED"`.
  Parsed by `parse_supervised_run_state`; junk → `None` (a broken state can never
  crash a turn). Terminal sentinel: `SUPERVISED_RUN_COMPLETED`.
- `workflow_state.supervised_run_intro_sent`: whether the current step's lesson was
  delivered.
- Database (`UserSupervisedRunProgress`, one row per user): ONLY final outcomes —
  declined at the offer, abandoned early, or completed the last step.
  Resetting a session mid-supervised run simply re-offers the supervised run.
- The DONE/UNDECIDED gate hydrates the DB row into the session state
  (hydrate-on-the-way-out, same pattern as the onboarding gate).
- An out-of-range persisted index (spec changed since) is not RUNNING: the
  flow self-heals (re-offers when no DB row exists).

## 5. Failure modes (deliberate)

| Failure | Behavior |
|---|---|
| Supervisor crash / no structured output / not built | Fail-open → normal agent answers |
| Checkpoint crash / blind engine / absent | Fail-closed → step not completed, user keeps going |
| `complete_condition` callable raises | Fail-closed → not completed (logged) |
| `get_supervised_run` fails / returns no steps | Feature silently OFF at build time (warning) |
| `features.supervised_run: false` in the manifest | Feature OFF even with `get_supervised_run` wired |

## 6. Where everything lives

| File | Role |
|---|---|
| `semente/domain/base.py` + `semente/domain/__init__.py` | `SupervisedRun`, `SupervisedRunStep`, `DomainSpec.get_supervised_run` (engine-free seam) |
| `semente/schemas/supervised_run.py` | `SupervisedRunDecision`, `CompletionCheck` |
| `semente/schemas/workflow_state.py` | supervised_run position (`parse_supervised_run_state`, `SUPERVISED_RUN_COMPLETED`) |
| `semente/agents/supervised_run_agent.py` | BOTH agents: supervisor (`build_supervised_run_agent`) + checkpoint (`build_supervised_run_check_agent`), seam resolver, announcement builder |
| `semente/agents/welcoming_agent.py` | supervised_run-offer stage + `supervised_run_offer_menu` (from step ids) |
| `semente/core/semente_agent.py` | routing (`SupervisedRunStatus`), decision application, `_check_supervised_run_completion`, `_advance_supervised_run_step`, `get_agent()` wiring |
| `semente/tools/supervised_run_tools.py` | `set_supervised_run_choice` (+ `mark_supervised_run_completed` persistence) |
| `semente/database/models.py` | `UserSupervisedRunProgress` |
| `semente/configs/prompts/defaults/agents.yml` | generic contracts: `supervised_run_agent`, `supervised_run_check_agent`, offer stage; fallback texts (`closing_default`, `abandon_default`) |
| `semente/configs/prompts/defaults/tools.yml` | `set_supervised_run_choice` result texts |
| `semente/cli/{config_cmd,init_cmd,templates,supervised_run_scaffold}.py` | `config enable/disable supervised_run`, `init --supervised-run`, example scaffold + safe auto-wiring |
| `tests/agent/test_supervised_run_flow.py`; `tests/test_cli_{config,init,cli}.py` | behavior coverage (47 supervised_run tests + CLI) |
| `docs/guide/{domain-api,cli,manifest}.md` | user-facing docs |

## 7. CLI support

```bash
semente init my-app --supervised-run        # or interactively asked y/N
semente config enable supervised_run        # flag + plants working example + wires the spec
semente config enable supervised_run --force  # overwrites only the example files
semente config disable supervised_run       # flag only — user files never deleted
```

`config enable supervised_run`:

1. sets `features.supervised_run: true` in the manifest;
2. writes `domain/supervised_run.py` (kept if it exists, unless `--force`) — a
   runnable 2-step example demonstrating both condition kinds;
3. wires `get_supervised_run=get_supervised_run` into the `DomainSpec` call — only when
   provably safe (single `domain_spec = DomainSpec(...)` assign found via
   `ast`, kwarg inserted before the close paren, result verified with
   `compile()`); otherwise prints the one-line manual instruction. The
   import is `from .supervised_run import get_supervised_run` (relative — cannot collide
   with the framework's `semente.domain`).

## 8. Prompt templates (the `{keys}`)

`agents.yml` ships the generic contracts; per language, an app overrides the
yml (localized files under the prompt dir), the domain supplies the content.

- `supervised_run_agent.instructions` ← `{step_instructions}` (lesson + forward
  rule, from the current `SupervisedRunStep`), `{abandon_text}`, `{supervised_run_state}`
  (progress + `lesson_delivered` + `<history_context>`).
- `supervised_run_check_agent.instructions` ← `{supervised_run_state}` (current step id,
  history, and the `{complete_condition}` string). The judged turn arrives
  as the run's input (`completion_payload`).
- `supervised_run_check_agent.completion_announcement` ← `{step_id}`, `{next_lesson}`.
- Welcoming: `instructions_supervised_run` ← `{user_name}`, `{supervised_run_menu}`
  (`SupervisedRun.offer` or the numbered ids menu); persona stage point 7 uses
  `{closing_the_identification}`.

## 9. Testing

```bash
.venv/bin/python -m pytest tests/agent/test_supervised_run_flow.py -q   # supervised_run core (47)
.venv/bin/python -m pytest tests/ -q                              # full suite
```

Known baseline noise (pre-existing on clean HEAD, unrelated to the
supervised_run): `test_cli_status.py::test_status_env_missing`,
`test_manifest.py` (2), `test_wizard.py::test_effective_env_file_fills_gaps`
— env-file parsing behavior in this workspace.

## 10. Decision log

| Date | Decision |
|---|---|
| 2026-10-14 v1 (first attempt, never committed) | Hardcoded 3-step flow (enum states + per-step yml keys) — discarded as the base for generalization; kept: supervisor pattern, decision schema, fail-open, DB-only-final-outcome. |
| 2026-10-14 v2 | Generalization: `SupervisedRun`/`SupervisedRunStep` seam; `DomainSpec.get_supervised_run` callable (mirrors `instructions`/`tools`); structured step fields; offer/closing/abandon texts; `features.supervised_run` toggle; state → step index; feature fully off without the seam. |
| 2026-10-14 (CLI) | `config enable supervised_run` scaffolds a working example + auto-wires the spec (safe-gated, manual-instruction fallback); `init --supervised-run` + interactive y/N; disable = flag only. |
| 2026-10-14 v3 | Step reshaping: keep `id`+`lesson` only; `forward_condition` (text) → supervisor prompt; `complete_condition` (str → checkpoint agent / callable → pipeline) judged **after a forwarded turn** with the single-agent output; callable receives `(session_state, user_text, agent_reply)`; supervisor no longer decides completion (`SupervisedRunDecision.step_completed` removed); completion announced by APPENDING congrats + next lesson (or closing) to the same reply; new step born lesson-delivered; offer menu from ids. |
| 2026-10-14 v3.1 | Both agents consolidated into one file (`semente/agents/supervised_run_agent.py`); `semente/agents/supervised_run_check_agent.py` deleted; yml tags unchanged. |
| 2026-10-15 (de-Pasto-Legal) | Last Pasto Legal remnants removed from the supervised run feature: the supervisor's geo-attachment marker became the `supervised_run_agent.geo_attachment_note` prompt key in `agents.yml` (fallback in code; tag `anexo` → `geo_attachment`), and the Portuguese example replies in `tools.yml` `set_supervised_run_choice` results are now English. 49 supervised run tests. |
| 2026-10-15 (rename) | The feature was renamed **tutorial → supervised run** everywhere: `Tutorial`/`TutorialStep` → `SupervisedRun`/`SupervisedRunStep`, `get_tutorial` → `get_supervised_run`, `features.tutorial` → `features.supervised_run`, yml tags `tutorial_agent`/`tutorial_check_agent` → `supervised_run_agent`/`supervised_run_check_agent`, tool `set_tutorial_choice` → `set_supervised_run_choice`, session fields `tutorial_state`/`tutorial_intro_sent` → `supervised_run_state`/`supervised_run_intro_sent`, DB table `user_tutorial_progress` → `user_supervised_run_progress`, CLI `--tutorial` → `--supervised-run` and `config enable/disable supervised_run`, `TUTORIAL.md` → `SUPERVISED_RUN.md`. Breaking: the seam, manifest flag, CLI args, prompt keys and the persisted table/fields all changed shape — apps must update `domain/` and re-create the DB. |

## 11. Open items / ideas (not decided — candidates only)

- Localized (e.g. pt-BR) overrides of the default supervised_run prompts for
  real deployments; today the defaults are English and the domain writes
  step content in the users' language.
- The supervisor's geo-attachment marker (in `_run_supervised_run_supervisor`)
  is a hardcoded detail kept from the first attempt — genericize if the
  concept of "attachments" appears in domain-taught steps.  →  **RESOLVED
  2026-10-15**: it now reads the `supervised_run_agent.geo_attachment_note`
  prompt key (tag renamed `<anexo>` → `<geo_attachment>`).
- Possibly expose the supervised run state to the debug panel / metrics later.

---
_When resuming: read §2–§5 for the contract, §10 for what/why, and `git log`
on this branch (`develop`, uncommitted workdir) for the exact shape of the
last change. Append decisions with a new date row._