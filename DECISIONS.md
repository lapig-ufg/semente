# Development Log — `feat/cli-commands`

> **⚠️ THIS FILE MUST BE DELETED at the end of the development of this
> branch, before merging into `develop`.**
>
> It is a scratchpad for decisions made while developing the CLI
> commands update. Do not merge it, do not commit it in the final
> merge — delete it first.

## Decisions

1. **Remove `semente config enable/disable`.** Their `feature enable/disable`
   replacements under `semente feature` own feature toggling; keeping both
   meant two ways to do the same thing. `config` keeps `set` and `channel`.
2. **`feature add` falls back to `enable` for framework-internal features**
   (`tts`, `summarization`, `guardrails`). Only `guardrails` has an
   app-side example to scaffold (`domain/guardrails_example.py`) — for
   the others `add` prints a "nothing to scaffold" note and enables it.
3. **`feedback_workflow` and `feedback` merged into `interaction_assessment`.**
   They were two gates of the same per-turn loop (the schema is even
   `semente/schemas/interaction_assessment.py`): `feedback_workflow` gated
   the satisfaction/persistence/persona pipeline, `feedback` gated the DPO/SFT
   capture window. One toggle now covers both, keeping the nested config
   (`enable` + `window_size`). The harness reads the gate via
   `Harness._interaction_assessment_enabled()` (bool/dict/FeedbackConfig
   aware). Legacy manifest keys still load, merged into the new key with a
   deprecation warning (same pattern as `pii_guardrail` → `guardrails`);
   an explicit `interaction_assessment` key wins entirely.
4. **Feature names follow kebab-case** (all lowercase, words separated by
   `-`): the merged feature is spelled `interaction-assessment` in the
   manifest and CLI catalog. Legacy spellings (`feedback_workflow`,
   `feedback`, and the snake_case `interaction_assessment` intermediate)
   still load, normalized to the kebab-case key. Python identifiers and
   schema/property names stay snake_case (`schemas/interaction_assessment.py`).
5. **Help on errors.** Running a group command without its subcommand
   (`semente feature`, `semente config`) prints that group's help + exit 1 —
   not the top-level help. Bad arguments/missing values print the help of the
   command where the error happened, like `-h` (custom `HelpOnErrorParser`
   overriding `argparse`'s `error()`; exit code stays 2).