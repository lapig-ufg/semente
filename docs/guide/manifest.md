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
features:                    # all default to true
  tts: true                  # attach TTS tool to the welcoming agent
  feedback_workflow: true    # satisfaction/persona feedback loop
  summarization: true        # rolling conversation summary
  pii_guardrail: true        # PII/LGPD redaction stage
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

## Feature toggles

| Toggle | When `false` |
|---|---|
| `tts` | The welcoming agent is built without the TTS tool. |
| `feedback_workflow` | The satisfaction/persona feedback loop is omitted from the run. |
| `summarization` | The rolling conversation summary stage is omitted. |
| `pii_guardrail` | The PII redaction stage is omitted. |

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
| `APP_ENV` | `development`, `staging`, or `production` (default `development`) |
| `DATABASE_TYPE` | `sqlite` (dev) or `postgres` (prod) |
| `SEMENTE_MANIFEST` | Path to the manifest (default `semente.yaml`) |
| `SEMENTE_PROMPTS_DIR` | Prompts directory (overridden by manifest `prompts_dir`) |
| `TTS_MODEL` | TTS model id (default `gemini-3.1-flash-tts-preview`) |
| `POSTGRES_*` | PostgreSQL connection (prod) |
| `PGVECTOR_*` | PgVector connection (knowledge base) |
| `WHATSAPP_*` | WhatsApp Business API credentials |
| `VALKEY_*` | Valkey/Redis (WhatsApp debouncing, prod) |
| `GEE_*` | Earth Engine service account (geospatial domains) |
| `S3_*` | S3-compatible storage (media, prod) |

See `.env.example` in the repository for the full list.
