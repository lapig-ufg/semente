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
   (`tts`, `summarization`, `feedback_workflow`, `feedback`). Only `guardrails`
   has an app-side example to scaffold (`domain/guardrails_example.py`) — for
   the others `add` prints a "nothing to scaffold" note and enables it.