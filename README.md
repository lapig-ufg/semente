# Semente 🌱

**Semente** is a multi-agent AI chat framework for land use and agriculture.
It was extracted from [Pasto Legal](https://github.com/lapig-ufg/pasto-legal)
(LAPIG/UFG) — an AI assistant that delivers satellite-based pasture diagnostics
to Brazilian ranchers over WhatsApp.

Semente keeps the domain-neutral engine (multi-agent workflow, WhatsApp +
Streamlit channels, persona/feedback loop, PII guardrails, i18n prompts, TTS)
and lets you grow a new land-use assistant by supplying a **domain** — tools,
knowledge base, skills, and prompts.

> *Pasto Legal was the first seed.*

📖 **Full documentation:** https://leandroleal.github.io/semente (source in [`docs/`](docs/)).

---

## Quickstart — deploy the Toy App

The **Toy App** (`examples/echo_domain/`) is the minimal Semente app: one `echo`
tool, no knowledge base. Use it to verify the framework boots, then copy it as
the starting point for your own app.

### 1. Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (or pip)
- A Google Gemini API key (or [Ollama](https://ollama.com) for local models)

### 2. Install

```bash
git clone https://github.com/leandroleal/semente.git
cd semente
uv venv .venv && source .venv/bin/activate
uv pip install -e .
```

### 3. Configure

```bash
cd examples/echo_domain
cp .env.example .env
# edit .env → set GOOGLE_API_KEY=your-gemini-api-key
```

### 4. Run (Streamlit)

```bash
export SEMENTE_MANIFEST=semente.yaml
semente launch streamlit
```

Open **http://localhost:8501** and chat — the Echo assistant replies
`Echo: <your message>`.

### 5. Deploy to production (WhatsApp)

```python
# main.py
from semente.build import build_app

app = build_app("semente.yaml")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=3000, reload=True)
```

```bash
python main.py          # FastAPI WhatsApp webhook on :3000
ngrok http 3000         # expose it, then set the WhatsApp webhook URL
```

Requires `WHATSAPP_*` and `VALKEY_*` env vars (see `.env.example` and the
[deployment guide](docs/deployment/toy-app.md)).

---

## How it works

```
User (WhatsApp / Streamlit)
        │
        ▼
   Semente workflow
   ├── Input step (media → text)
   ├── PII guardrail
   ├── Onboarding check (terms)
   ├── Parallel: summarization + feedback loop + your agent
   ├── Remediation merge
   └── Output step (TTS)
        │
        ▼
   Your domain (tools, knowledge, skills, prompts)
```

You write two things:

**`domain/__init__.py`** — your domain:

```python
from agno.tools import tool
from semente.domain import DomainSpec

@tool(description="Echo the given message back to the user.")
def echo(message: str) -> str:
    return f"Echo: {message}"

domain_spec = DomainSpec(name="My App", tools=[echo])
```

**`semente.yaml`** — your manifest:

```yaml
name: my-app
domain_module: domain
channels: [streamlit]
```

## Manifest reference

```yaml
name: my-app                 # app name (workflow name)
language: pt-BR              # optional; loads prompts/<lang>/ if present
domain_module: domain        # import path exposing `domain_spec`
prompts_dir: domain/prompts  # optional; explicit prompts dir
engine: agno                 # agno (default) | adk | bare
channels: [streamlit]        # streamlit and/or whatsapp
features:                    # all default to true
  tts: true                  # TTS tool on the welcoming agent
  feedback_workflow: true    # satisfaction/persona feedback loop
  summarization: true        # rolling conversation summary
  pii_guardrail: true        # PII/LGPD blocking step
models:                      # optional override of env-var model config
  primary: { provider: google, id: gemini-3.5-flash-lite }
  fallback: { provider: ollama, id: gemma4:31b-cloud }
```

Model config defaults to `.env` vars (`PRIMARY_MODEL_PROVIDER`,
`PRIMARY_MODEL_ID`, `FALLBACK_*`); the manifest `models` block overrides them.
The `engine` field (or `SEMENTE_ENGINE` env var) swaps the agent engine — see
[Engines](docs/guide/engines.md).

## Documentation

| Page | Content |
|---|---|
| [Getting Started](docs/guide/getting-started.md) | Install + first app |
| [The Domain](docs/guide/domain.md) | `DomainSpec` reference |
| [Manifest Reference](docs/guide/manifest.md) | Every `semente.yaml` option |
| [Prompts & i18n](docs/guide/prompts.md) | YAML prompts + localization |
| [Channels](docs/guide/channels.md) | WhatsApp + Streamlit |
| [Engines](docs/guide/engines.md) | agno / adk / bare backends |
| [Deploy the Toy App](docs/deployment/toy-app.md) | Full deployment walkthrough |
| [Pasto Legal](docs/showcase/pasto-legal.md) | The first seed, as a showcase |

Build the docs site locally:

```bash
cd docs
npm install
npm run dev     # http://localhost:5173
```

## License

GPL-3.0-or-later. Semente is a derivative of Pasto Legal (LAPIG/UFG) and must
remain open. See `LICENSE`.
