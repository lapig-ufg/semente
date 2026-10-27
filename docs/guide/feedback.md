# Feedback & Fine-Tuning

The `interaction-assessment` feature turns ordinary conversations into
training data. It runs on every turn (when enabled), evaluates user
satisfaction, persists results to the database, and captures DPO and SFT
trajectories — all domain-neutral and driven by the harness, not by your
tools.

One toggle covers both the behavior and the data capture:

```yaml
# semente.yaml
features:
  interaction-assessment:
    enable: true                   # the whole loop below (default true)
    window_size: 5                 # rolling SFT trajectory window (default 5, min 1)
```

It also accepts a plain boolean (`interaction-assessment: false`), which
expands to `{enable: <bool>, window_size: 5}`.

> **Legacy keys:** the old `feedback_workflow` and `feedback` toggles still
> load (merged into `interaction-assessment`, with deprecation warnings) —
> rename them in your manifest. With only legacy keys, `feedback: false`
> disables the feature like before.

## The satisfaction agent

When `interaction-assessment` is on, every non-onboarding turn the
**satisfaction evaluation agent** reads the last exchange plus the current
message and returns a structured `Effectiveness`
(`semente/schemas/interaction_assessment.py`):

- `level` — satisfaction 1–5 (≤ 2 unsatisfied, ≥ 4 satisfied)
- `changed_topic` — whether the user moved off the failed answer

This is an extra LLM call per turn; set `interaction-assessment: false` to
skip it entirely. Disabling it also disables the following persistence steps.

## The DPO two-phase loop

Unsatisfied turns open a **remediation cycle** captured over exactly two
turns into a `NegativeFeedback` row (`semente/database/models/feedback.py`):

| Turn | What happens | Row state |
|---|---|---|
| **n** (level ≤ 2, no topic change) | The harness stores the rejected answer (`prompt` + `rejected`), replies with a **remediation** answer instead of the raw agent output, and marks `assessment.pending` with the row id | `chosen` empty, pair open |
| **n + 1** (the user evaluates the remediation) | Positive (level ≥ 4) completes the row's `chosen` half with `approved: true`; negative (level ≤ 2) records `approved: false` + `rejected_new` (kept for manual analysis, **not** for training) | pair closed, `history` written |

Rules:

- A cycle never re-opens on the closing turn — a still-frustrated user opens a
  *fresh* cycle one turn later.
- `_finalize_pending_history` (after the run is appended) writes the cycle's
  `history` onto the row and clears the pending, so a crash between turns
  leaves a retryable pending rather than a broken state.

## The SFT branch

When `interaction-assessment.enable` is on,
clean agent runs append their trajectory to
`session_state["recent_agent_runs"]`. Onboarding and remediation-cycle turns
are **never** recorded — only clean, working exchanges, capped at the
`window_size` most recent runs. When a positive turn fires, the window is
persisted as a `PositiveFeedback` row, masked of PII, matching the
`SFTDatasetRow` / `DPODatasetRow` schemas in
`semente/schemas/fine_tuning.py`:

```python
class MessageRow(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: Optional[str] = None
    tool_calls: ...
    tool_call_id: ...

class SFTDatasetRow(BaseModel):
    messages: List[MessageRow]

class DPODatasetRow(BaseModel):
    prompt: str | List[MessageRow]
    chosen: str | List[MessageRow]
    rejected: str | List[MessageRow]
```

> The rows currently live in these tables only — a dataset exporter is not
> part of the package yet; the schemas define the target format.

## Where this runs in the pipeline

```
├── _summarize_conversation        # every 6 turns (interaction-assessment off still runs this)
├── _process_feedback              # gated by interaction-assessment
│   ├── _evaluate_satisfaction     # structured Effectiveness
│   ├── _persist_feedback          # DPO two-phase / SFT windows
│   └── _manage_persona            # persona agent (PersonaUpdate)
├── _run_single_agent              # records trajectory only when interaction-assessment.enable
│   └── _generate_apology          # overrides the output when a cycle is open
```

See the [Architecture](/architecture/) page for where this sits in the full
turn pipeline. Persisted trajectories are sanitized field-by-field through
the app's [guardrail chain](/guide/guardrails) before storage.