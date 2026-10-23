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
3. **`feedback_workflow` and `feedback` merged into `interaction-assessment`.**
   They were two gates of the same per-turn loop (the schema is even
   `semente/schemas/interaction_assessment.py`): `feedback_workflow` gated
   the satisfaction/persistence/persona pipeline, `feedback` gated the DPO/SFT
   capture window. One toggle now covers both, keeping the nested config
   (`enable` + `window_size`). The harness reads the gate via
   `Harness._interaction_assessment_enabled()` (bool/dict/FeedbackConfig
   aware). Legacy manifest keys (`feedback_workflow`, `feedback`, and the
   snake_case `interaction_assessment` intermediate) still load, merged into
   the new key with a deprecation warning; an explicit kebab-case key wins
   entirely.
4. **Feature names follow kebab-case** (all lowercase, words separated by
   `-`): the merged feature is spelled `interaction-assessment` in the
   manifest and CLI catalog. Legacy spellings (`feedback_workflow`,
   `feedback`, and the snake_case `interaction_assessment` intermediate)
   still load, normalized to the kebab-case key. Python identifiers and
   schema/property names stay snake_case (`schemas/interaction_assessment.py`).
5. **Help on errors.** Running a command group without its subcommand
   (`semente feature`, `semente config`) prints that group's help + exit 1 —
   not the top-level help. Bad arguments/missing values print the help of the
   command where the error happened, like `-h` (custom `HelpOnErrorParser`
   overriding `argparse`'s `error()`; exit code stays 2).
6. **`config` unrolled and deleted.** `channel` is its own command (like
   `feature`): `ls`, `actives`, and flag-style toggles —
   `semente channel whatsapp --enable` / `--disable` — replacing the old
   `channel add/remove` subcommands. `feature` moved to the same flags
   (`feature <name> --enable|--disable`), dropping its `enable`/`disable`
   subcommands; both gained `actives`, and a bare `feature/channel <name>`
   shows the item's status plus a hint naming both toggle options (the hint
   is always present). `provider` owns provider/model-id/fallback/keys:
   `primary`/`fallback` set the manifest `models:` block, `fallback --disable`
   removes it, `key` writes secrets to `.env` (hidden input, masked echo,
   empty answer keeps the existing value). The remaining `config set` keys
   (`name`, `language`, `domain_module`, `prompts_dir`, `engine`) have no CLI
   anymore — edit `semente.yaml` directly. Shared manifest helpers moved from
   `config_cmd.py` to `semente/cli/common.py`.
   **Gotcha found while testing:** `wizard.DEFAULT_ENV_PATH` freezes at
   import time — under pytest, `monkeypatch.chdir` does NOT redirect it, and
   tests wrote a fake `.env` into the repo root (it didn't exist before, so
   nothing was lost, but it could have been). `provider key` now resolves
   `Path.cwd() / ".env"` at call time.