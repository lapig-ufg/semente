# CLI Reference

The `semente` command manages the full app lifecycle — create, configure,
inspect, and run. All commands work from the app directory (where
`semente.yaml` lives).

```bash
semente init          # scaffold a new app
semente feature       # manage features (list, add, enable, disable)
semente config        # edit the manifest
semente status        # app overview + doctor checks
semente launch        # run an interface
```

## `semente init [directory]`

Scaffolds a minimal working app, modeled on the [Pasto Legal](https://github.com/lapig-ufg/pasto-legal)
reference implementation:

```
my-app/
├── semente.yaml            # manifest: features on, streamlit channel, model block
├── .env.example            # every variable group, commented
├── domain/
│   ├── __init__.py        # domain_spec with an example echo tool
│   └── prompts/           # agents.yml, tools.yml, hooks.yml (bundled defaults)
├── main.py                 # FastAPI entry (WhatsApp webhook)
└── .gitignore
```

Options:

| Flag | Description |
|---|---|
| `--name` | App name (default: directory name) |
| `--language` | Agent language (default: `en`) |
| `--provider` | `google` (default) or `ollama` |
| `--force` | Overwrite existing files |
| `--non-interactive` | Never prompt (use defaults) |

Existing files are never overwritten without `--force`. If `semente.yaml`
already exists, init refuses and points to `semente feature` / `semente config`.

## `semente feature`

Manages the manifest's `features` block. Resolution: `SEMENTE_MANIFEST` env
var, then `./semente.yaml`. Without a manifest it exits with an actionable
hint.

```bash
semente feature ls                    # every feature + status (enabled/disabled/default)
semente feature add guardrails        # scaffold an example + enable
semente feature add tts               # framework-internal: just enable
semente feature enable tts
semente feature disable tts           # only the manifest toggles — code is left alone
```

Supported features:

| Feature | Meaning |
|---|---|
| `tts` | TTS tool on the welcoming agent (audio replies) |
| `summarization` | Rolling conversation summary (every 6 turns) |
| `interaction_assessment` | Satisfaction/persona loop, remediation cycles, DPO/SFT capture (`{enable, window_size}`) |
| `guardrails` | Pluggable input guardrails declared in `DomainSpec` |

`add` writes an app-side example when one exists — today only `guardrails`
(re-checking your `domain/` for a `guardrails_example.py` it creates,
never overwriting an existing file) — and enables the feature. For
framework-internal features `add` behaves like `enable`: the framework owns
their behavior; there is no app code to scaffold.

> `disable` never deletes your code. It flips the manifest key; re-run
> `semente feature enable <name>` to turn it back on.

## `semente config`

Edits `semente.yaml` in place (keys and channels). Resolution:
`SEMENTE_MANIFEST` env var, then `./semente.yaml`. Without a manifest it
exits with an actionable hint.

```bash
semente config set language pt-BR
semente config set engine bare        # engines: agno, adk, bare
semente config set models.primary.id gemini-2.0-flash
semente config set models.fallback.provider ollama
semente config channel add whatsapp   # channels: streamlit, whatsapp
semente config channel remove streamlit
```

Valid keys for `set`: `name`, `language`, `domain_module`, `prompts_dir`,
`engine`, `models.primary.provider`, `models.primary.id`,
`models.fallback.provider`, `models.fallback.id`.

## `semente status`

Prints the app at a glance (rich tables):

- **App** — name, language, engine, domain module, prompts dir, manifest path
- **Channels** — enabled channels
- **Features** — on/off (absent keys default to enabled)
- **Models** — primary/fallback provider and id
- **Environment** — required model variables, present/missing, API keys masked
- **Doctor** — static checks: the domain module exposes `domain_spec`
  (AST-parsed, never imported), and the prompts dir has the three YAML files

Without a manifest it prints a friendly `semente init` hint (exit 0 — it's
informational, not an error).

## `semente launch <interface>`

Starts an app interface.

```bash
semente launch streamlit          # your app (reads SEMENTE_MANIFEST or ./semente.yaml)
semente launch streamlit --demo  # the built-in default agent — no app files needed
```

The first run in a folder triggers the **setup wizard**: missing model values
(provider, model ID, API key) are asked interactively, saved to `./.env`, and
never asked again. Only the gaps are asked; exported shell variables count as
set. Non-interactive contexts (Docker, CI) get a warning listing what is
missing instead of prompts.

`semente launch whatsapp` explains that WhatsApp is a webhook channel — it
runs via `python main.py` (FastAPI), not a launcher. Future interfaces
(Instagram, ...) will appear here.