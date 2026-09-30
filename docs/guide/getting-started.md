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

## The two files you write

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
export SEMENTE_MANIFEST=semente.yaml
export GOOGLE_API_KEY=your-gemini-key
semente streamlit
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

- [The Domain](/guide/domain) — everything `DomainSpec` can hold
- [Manifest Reference](/guide/manifest) — every `semente.yaml` option
- [Deploy the Toy App](/deployment/toy-app) — a complete runnable example
