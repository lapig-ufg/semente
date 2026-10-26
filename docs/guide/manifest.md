# Manifest Reference

The manifest (`semente.yaml`) is the app-level configuration. Every field is
optional except `name` and `domain_module`.

```yaml
name: my-app                 # app name
language: pt-BR              # optional; loads prompts/<lang>/ if present
domain_module: domain        # import path exposing `domain_spec`
prompts_dir: domain/prompts  # optional; explicit prompts dir (overrides language)
engine: agno                 # agno (default) | adk | bare
channels: [streamlit]        # streamlit and/or whatsapp
features:                    # booleans default to true (terms-acceptance: false)
  tts: true                  # attach TTS tool to the welcoming agent
  interaction-assessment: true  # satisfaction/persona loop + DPO/SFT capture, or {enable: true, window_size: 5}
  summarization: true        # rolling conversation summary
  guardrails: true           # pluggable input guardrails (DomainSpec.guardrails)
  terms-acceptance:          # onboarding terms gate — off unless enabled
    enable: true
    file: domain/terms.md    # reference terms text (required when enabled)
    url: https://example.com/terms  # optional: link sent in the first message
models:                      # optional override of env-var model config
  primary: { provider: google, id: gemini-3.5-flash-lite }
  fallback: { provider: ollama, id: gemma4:31b-cloud }
```

## Fields

| Field | Type | Default | Description |
|---|---|---|---|
| `name` | `str` | — | App name; formatted into the onboarding prompts and shown in `semente status`. |
| `language` | `str` | `en` | Selects `prompts/<language>/` when it exists. |
| `domain_module` | `str` | `domain` | Import path of the module exposing `domain_spec`. |
| `prompts_dir` | `str` | — | Explicit prompts directory (relative to cwd). Overrides `language`. |
| `engine` | `str` | `agno` | Agent engine: `agno`, `adk`, or `bare`. See [Engines](engines.md). |
| `channels` | `list` | `[streamlit]` | `streamlit` and/or `whatsapp`. |
| `features` | `dict` | all `true` (except `terms-acceptance`) | Feature toggles (see below). |
| `models` | `dict` | — | Overrides the `.env` model config. |

## Engine resolution

The manifest `engine` field is the first resolver. When absent, Semente falls
back to the `SEMENTE_ENGINE` environment variable, then the `agno` default:

```bash
export SEMENTE_ENGINE=adk    # applies when the manifest has no engine field
```

## Feature toggles

| Toggle | When off |
|---|---|
| `tts` | The welcoming agent is built without the TTS tool. |
| `interaction-assessment` | The whole loop — satisfaction agent, DPO/SFT persistence and capture, persona updates, and remediation — is omitted from the run. Boolean or `{enable, window_size}` — see [Feedback & Fine-Tuning](feedback.md). |
| `summarization` | The rolling conversation summary stage is omitted. |
| `guardrails` | The app's guardrail chain (`DomainSpec.guardrails`) is skipped everywhere — see [Guardrails](guardrails.md). |
| `terms-acceptance` | The terms stage is skipped: new users go straight to the persona stage (and the DB gate never asks for an acceptance row). Off by default. |

Absent keys default to enabled, **except `terms-acceptance`, which is off
unless enabled** — a domain-neutral framework cannot assume the app has terms
to accept. Turn the whole subsystem off with
`interaction-assessment: false` (it also saves an LLM call per turn).

### Terms acceptance

When enabled, the welcoming agent's first message asks the user to accept the
Terms of Use, and `accept_terms_and_conditions` records the acceptance in the
`user_terms_acceptance` table. `file` is the reference text the agent may quote
if the user asks questions (the full text is never pasted unprompted); `url` is
optional and, when set, is sent verbatim in that first message. A missing or
unreadable `file` fails at startup — consent is never recorded without terms
the user could have read. Paths are resolved relative to `semente.yaml`.

The first `semente feature terms-acceptance --enable` (or
`feature add terms-acceptance`) scaffolds `domain/terms_example.md` and
configures `file` for you; replace that example with your real terms. Existing
files and an already-configured `file` are never overwritten.

### Legacy `terms_text`

The terms reference used to live in `agents.yml` (`welcoming_agent.terms_text`).
It now comes from `features.terms-acceptance.file`; apps can delete the old
key from their prompts.

> **Legacy aliases:** the old `features.feedback_workflow` and
> `features.feedback` keys still load (merged into
> `interaction-assessment`, with deprecation warnings) — rename them in
> your manifest.
>
> **Legacy alias:** the old `features.pii_guardrail` key still loads
> (normalized to `guardrails`, with a deprecation warning) — rename it in
> your manifest.

## Model resolution

Models are configured primarily through environment variables:

| Env var | Description |
|---|---|
| `PRIMARY_MODEL_PROVIDER` | `google` or `ollama` |
| `PRIMARY_MODEL_ID` | e.g. `gemini-3.5-flash-lite` |
| `FALLBACK_MODEL_PROVIDER` / `FALLBACK_MODEL_ID` | Optional fallback model |
| `GOOGLE_API_KEY` | Required for the `google` provider |
| `OLLAMA_API_KEY` / `OLLAMA_HOST` | For the `ollama` provider |

The manifest `models` block overrides these per-app:

```yaml
models:
  primary: { provider: google, id: gemini-3.5-flash-lite }
  fallback: { provider: ollama, id: gemma4:31b-cloud }
```

## Environment variables

Semente reads configuration from a `.env` file in the working directory
(loaded via `python-dotenv`).

| Variable | Purpose |
|---|---|
| `APP_ENV` | `development` (default), `stagging`, or `production` |
| `DATABASE_TYPE` | `sqlite` (dev) or `postgres` (prod) |
| `SEMENTE_MANIFEST` | Path to the manifest (default `semente.yaml`) |
| `SEMENTE_ENGINE` | Engine when the manifest has no `engine` field (`agno`, `adk`, `bare`) |
| `SEMENTE_DEMO` | Set by `semente launch streamlit --demo`; boots the built-in demo domain |
| `SEMENTE_PROMPTS_DIR` | Prompts directory (overridden by manifest `prompts_dir`) |
| `TTS_MODEL` | TTS model id (default `gemini-3.1-flash-tts-preview`) |
| `POSTGRES_*` | PostgreSQL connection (prod) |
| `PGVECTOR_*` | PgVector connection (knowledge base) |
| `WHATSAPP_*` | WhatsApp Business API credentials |
| `VALKEY_*` | Valkey/Redis (WhatsApp debouncing, prod) |
| `GEE_*` | Earth Engine service account (geospatial domains) |
| `S3_*` | S3-compatible storage (media, prod) |

See `.env.example` in the repository for the full list.
