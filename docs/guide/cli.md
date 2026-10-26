# CLI Reference

The `semente` command manages the full app lifecycle — create, configure,
inspect, and run. All commands work from the app directory (where
`semente.yaml` lives).

Help behavior: running a command group without its argument (`semente
feature`, `semente channel`, `semente provider`) prints that group's help;
any invalid argument prints the help of the command where the error
happened — equivalent to typing `-h` there.

```bash
semente init          # scaffold a new app
semente feature       # manage features (ls, actives, add, --enable/--disable)
semente channel       # manage channels (ls, actives, --enable/--disable)
semente provider      # primary/fallback models and API keys
semente status        # app overview + doctor checks
semente launch        # run an interface
```

## `semente init [directory]`

Scaffolds a minimal working app with the framework's bundled, domain-neutral
defaults:

```
my-app/
├── semente.yaml            # manifest: features, streamlit channel, model block
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
already exists, init refuses and points to `semente feature` /
`semente channel` / `semente provider`.

## `semente feature`

Manages the manifest's `features` block. Resolution: `SEMENTE_MANIFEST` env
var, then `./semente.yaml`. Without a manifest it exits with an actionable
hint. Toggling is flag-style: one of `--enable`/`--disable` is required, and
they are mutually exclusive. Typing `semente feature <name>` with no flag
prints that feature's status plus the exact commands to enable or disable it.

```bash
semente feature ls                              # every feature + status (enabled/disabled/default)
semente feature actives                          # currently active features only
semente feature add guardrails                  # scaffold an example + enable
semente feature add tts                         # framework-internal: just enable
semente feature tts --enable
semente feature tts --disable                   # manifest-only — code is left alone
```

Supported features:

| Feature | Meaning |
|---|---|
| `tts` | TTS tool on the welcoming agent (audio replies) |
| `summarization` | Rolling conversation summary (every 6 turns) |
| `interaction-assessment` | Satisfaction/persona loop, remediation cycles, DPO/SFT capture (`{enable, window_size}`) |
| `guardrails` | Pluggable input guardrails declared in `DomainSpec` |
| `terms-acceptance` | Onboarding terms gate: first-message consent + DB record (`{enable, file, url}`); **off by default** |

`add` writes an app-side example when one exists — today only `guardrails`
(it creates `domain/guardrails_example.py`, never overwriting an existing
file) — and enables the feature. For framework-internal features `add`
behaves like `enable`: the framework owns their behavior; there is no app
code to scaffold.

> `--disable` never deletes your code. It flips the manifest key; re-run
> `semente feature <name> --enable` to turn it back on.

## `semente channel`

Same flag style as `feature`, operating on the manifest `channels` list.

```bash
semente channel ls                    # every channel + status
semente channel actives               # enabled channels only
semente channel whatsapp --enable     # channels: + whatsapp
semente channel whatsapp --disable    # channels: - whatsapp
semente channel whatsapp              # status + the enable/disable hints
```

| Channel | Meaning |
|---|---|
| `streamlit` | Local web chat (dev-friendly UI with debug panel) |
| `whatsapp` | WhatsApp webhook channel (assembled by `build_app`; run via `main.py`) |

## `semente provider`

Manages the model configuration: providers, model ids, the optional
fallback, and the API keys. The `.env` model block is the base; a manifest
`models:` block overrides it — `primary`/`fallback` write that block, keys
(secrets) are written to `.env`, never to `semente.yaml`.

```bash
semente provider ls                              # effective config + missing keys
semente provider primary google --model gemini-2.0-flash
semente provider primary ollama                  # id untouched (.env / wizard handles it)
semente provider fallback ollama --model gemma4:31b-cloud
semente provider fallback --disable              # remove the fallback from the manifest
semente provider key google                      # hidden input -> GOOGLE_API_KEY in .env
semente provider key ollama                      # OLLAMA_HOST + OLLAMA_API_KEY
```

Providers: `google` (Gemini) and `ollama` (local). One `--model` flag is
accepted per `primary`/`fallback` call. `ls` marks provider keys as
`set`/`missing` against the effective environment (shell + `.env`).

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