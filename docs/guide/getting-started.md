# Getting Started

Semente is a Python framework (3.12+) built on [Agno](https://github.com/agno-agi/agno).
A Semente app is a **domain** (your tools + knowledge + prompts) plus a
**manifest** (`semente.yaml`). The framework assembles the multi-agent
pipeline (the `SementeAgent`) and channels around them.

## Install

```bash
pip install semente-agents
```

For geospatial domains, add the extras you need:

```bash
pip install "semente-agents[gee,weather,knowledge]"
```

| Extra | Provides |
|---|---|
| `gee` | Earth Engine, DuckDB, GeoPandas, xarray, shapely |
| `weather` | Open-Meteo forecast tools |
| `knowledge` | PgVector (vector KB for the Q&A agent) |

## First run — the setup wizard

The first time you run `semente launch streamlit` (with or without `--demo`)
in a folder, an interactive wizard checks the **effective environment** — your
shell variables plus the local `.env` — for the values the model needs:

```
Semente needs a few values to run the model (saved to .env, asked only once):
Model provider (google/ollama) [google]:
Model ID [gemini-3.5-flash-lite]:
GOOGLE_API_KEY: ********
Saved to .env.
```

- Only **missing** values are asked — a `.env` with just a gap fills that gap.
- Answers are saved to `./.env`, so the wizard never runs again.
- Exported shell variables count as already set (no nagging).
- Non-interactive contexts (Docker, CI) never prompt: a warning lists what is
  missing and the launch proceeds.

## Try the demo agent first

No app yet? Run the built-in default agent — it needs **no** `semente.yaml`,
no `domain/` module, and no prompts: just the wizard values above.

```bash
uv run semente launch streamlit --demo
```

This boots a clean, tools-less agent with the bundled default prompts — the
fastest way to check your model setup and see the chat pipeline (onboarding,
persona, feedback) working end-to-end.

Without `--demo`, the command requires a manifest — `./semente.yaml` or the
`SEMENTE_MANIFEST` env var — and exits with a hint pointing to `--demo` when
neither exists.

## The two files you write

Skip this section with `semente init` — it scaffolds both files (plus
`.env.example`, `main.py`, and prompt files) for you.

### 1. `domain/__init__.py` — your domain

```python
from agno.tools import tool
from semente.domain import DomainSpec

@tool(description="Echo the given message back to the user.")
def echo(message: str) -> str:
    return f"Echo: {message}"

domain_spec = DomainSpec(
    name="My App",
    tools=[echo],
)
```

### 2. `semente.yaml` — your manifest

```yaml
name: my-app
domain_module: domain
channels: [streamlit]
```

## Run it

```bash
export GOOGLE_API_KEY=your-gemini-key   # or let the first-run wizard ask
semente launch streamlit
```

That's it. The framework wires the onboarding, PII guardrail, feedback loop,
summarization, and your `echo` tool into a working chat.

## Project layout

```
my-app/
├── domain/
│   ├── __init__.py      # exposes `domain_spec`
│   ├── tools.py         # your Agno tools
│   ├── knowledge.py     # optional vector KB
│   └── prompts/         # optional domain prompts (see Prompts & i18n)
├── semente.yaml         # manifest
├── .env                 # secrets (API keys, DB, WhatsApp)
└── main.py              # optional FastAPI entry (WhatsApp)
```

## Next steps

- [CLI Reference](/guide/cli) — `init`, `config`, `status`, `launch`
- [The Domain](/guide/domain) — everything `DomainSpec` can hold
- [Manifest Reference](/guide/manifest) — every `semente.yaml` option
- [Deploy the Toy App](/deployment/toy-app) — a complete runnable example
