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
features:                    # booleans default to true
  tts: true                  # attach TTS tool to the welcoming agent
  feedback_workflow: true    # satisfaction/persona feedback loop
  summarization: true        # rolling conversation summary
  guardrails: true           # pluggable input guardrails (DomainSpec.guardrails)
  feedback: { enable: true, window_size: 5 }  # or a plain boolean — see Feedback & Fine-Tuning
models:                      # optional override of env-var model config
  primary: { provider: google, id: gemini-3.5-flash-lite }
  fallback: { provider: ollama, id: gemma4:31b-cloud }
```

## Fields

| Field | Type | Default | Description |
|---|---|---|---|
| `name` | `str` | — | App name; used as the agent name. |
| `language` | `str` | `en` | Selects `prompts/<language>/` when it exists. |
| `domain_module` | `str` | `domain` | Import path of the module exposing `domain_spec`. |
| `prompts_dir` | `str` | — | Explicit prompts directory (relative to cwd). Overrides `language`. |
| `engine` | `str` | `agno` | Agent engine: `agno`, `adk`, or `bare`. See [Engines](engines.md). |
| `channels` | `list` | `[streamlit]` | `streamlit` and/or `whatsapp`. |
| `features` | `dict` | all `true` | Feature toggles (see below). |
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
| `feedback_workflow` | The whole feedback loop — satisfaction agent, DPO/SFT persistence, persona updates, and remediation — is omitted from the run. |
| `feedback` | Only the SFT trajectory capture (the `recent_agent_runs` window) stops; satisfaction/behavior still run. Boolean or `{enable, window_size}` — see [Feedback & Fine-Tuning](feedback.md). |
| `summarization` | The rolling conversation summary stage is omitted. |
| `guardrails` | The app's guardrail chain (`DomainSpec.guardrails`) is skipped everywhere — see [Guardrails](guardrails.md). |

Absent keys default to enabled. Turn the whole subsystem off with
`feedback_workflow: false` (it also saves an LLM call per turn).

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
