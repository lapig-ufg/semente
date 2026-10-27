# Groot — the Semente documentation assistant

**Groot** is a minimal Semente app (`examples/groot/`) that reads **this very
documentation** and helps you with every aspect of it using Gemini: explaining
concepts, finding the right page, step-by-step guides, config and code examples,
troubleshooting and comparisons, in English or Portuguese. It is the
smallest useful example of a *domain*: three plain Python tools, no vector
database, no embeddings.

```
User ──► Streamlit chat ──► Harness ──► Agno agent (Gemini)
                                          ├── list_docs()
                                          ├── search_docs(query)
                                          └── read_doc(path)  ──► docs/**/*.md
```

Semente provides the pipeline (onboarding, guardrails, summarization, the Agno
engine, the chat UI). The example only supplies the **domain**: how to read the
docs.

## Prerequisites

- **Python 3.12+** and **uv** (or pip)
- A **Google Gemini API key**
- A clone of the repository (the agent reads its `docs/` folder)

## 1. Install and run

```bash
git clone https://github.com/lapig-ufg/semente.git
cd semente
uv venv .venv && source .venv/bin/activate
uv pip install -e .

cd examples/groot
cp .env.example .env          # set GOOGLE_API_KEY (or let the first-run wizard ask)
semente launch streamlit
```

Open `http://localhost:8501` and ask something:

> How do I enable terms acceptance?
> Qual a diferença entre as engines `agno` e `bare`?

The agent searches the docs, reads the relevant page and answers citing the
file it used (for example `guide/manifest.md`). It replies in your language and
reads the English or Portuguese pages accordingly.

## 2. The files

```
examples/groot/
├── semente.yaml              # manifest: engine agno, streamlit, Gemini model
├── .env.example
├── main.py                   # optional FastAPI entry (WhatsApp)
└── domain/
    ├── __init__.py           # the three tools + domain_spec
    └── prompts/
        ├── agents.yml        # the agent's instructions
        ├── tools.yml
        └── hooks.yml
```

### The manifest

```yaml
name: groot
language: en
domain_module: domain
prompts_dir: domain/prompts
engine: agno
channels:
- streamlit
features:
  onboarding: false          # answer right away, no welcome step
  tts: false
  summarization: true
  guardrails: true
  interaction-assessment: false   # skips one extra LLM call per turn
models:
  primary:
    provider: google
    id: gemini-3.5-flash-lite
```

### The domain — three tools

Each tool is a plain function decorated with `@tool` (see
[Domain API](/guide/domain-api)). Semente adapts them to the Agno engine.

```python
from semente import tool
from semente.domain import DomainSpec

@tool(description="Lists every page of the Semente documentation (path + title). ...")
def list_docs(language: str = "en") -> str: ...

@tool(description="Keyword search over the Semente documentation. ...")
def search_docs(query: str, language: str = "en", max_results: int = 5) -> str: ...

@tool(description="Reads one documentation page in full. ...")
def read_doc(path: str) -> str: ...

domain_spec = DomainSpec(
    name="groot",
    tools=[list_docs, search_docs, read_doc],
)
```

| Tool | What it does |
|---|---|
| `list_docs(language)` | Lists the pages (`en` = `docs/`, `pt` = `docs/pt/`) with their titles |
| `search_docs(query, language, max_results)` | Scores every section (split at `#`/`##`/`###` headings) by keyword hits, heading hits weigh more, and returns the best ones with their path |
| `read_doc(path)` | Returns one page. The path is resolved inside the docs folder only — `..` and non-`.md` files are refused |

The full source is in
[`domain/__init__.py`](https://github.com/lapig-ufg/semente/blob/main/examples/groot/domain/__init__.py).

### The instructions

`domain/prompts/agents.yml` tells the agent to search first, read the page when
the hit is incomplete, cite the path, never invent commands and admit when the
docs do not cover the question:

```yaml
single_agent:
  name: "Groot"
  instructions_default: |
    You are Groot. Your mission is to help users UNDERSTAND the Semente framework ... Everything you know comes from the official documentation, reached through your tools.
    ONLY the official documentation, which you reach through your tools.
    1. Call `search_docs` with a few keywords from the question. ...
    2. When a search hit looks relevant but incomplete, call `read_doc` ...
    3. Answer from what you read. Cite the page path(s) you used.
    4. If the docs do not cover the question, say so plainly.
```

Everything not defined here (onboarding, persona…) falls back to Semente's
neutral defaults — see [Prompts & i18n](/guide/prompts).

## No onboarding

By default Semente runs a short onboarding (the user's **name** and **role**)
before the main agent answers. A docs bot should just answer, so Groot turns it
off in `semente.yaml`:

```yaml
features:
  onboarding: false
```

Every turn goes straight to Groot and its documentation tools, with no welcome
step and no persona to fill in. See the
[Manifest Reference](/guide/manifest#feature-toggles).
## 3. Use a different docs folder

By default the tools read `../../docs` relative to the example. Point them
anywhere with an environment variable:

```ini
# .env
SEMENTE_DOCS_DIR=/path/to/another/docs
```

The same example becomes a Q&A bot for any Markdown folder: change the folder
and the prompt in `agents.yml`.

## 4. Serve it on WhatsApp

Enable the channel and follow the production steps of the
[Toy App guide](/deployment/toy-app#_6-deploy-to-production-whatsapp):

```bash
semente channel whatsapp --enable
python main.py
```

## Going further

- **Better retrieval:** replace `search_docs` with a vector knowledge base
  (`DomainSpec.knowledge`) — see [The Domain](/guide/domain).
- **Other engines:** set `engine: adk` or `bare` — see [Engines](/guide/engines).
- **Safety:** add [guardrails](/guide/guardrails) if users may paste secrets.
- **AI-friendly source:** the site also publishes
  [`/llms.txt`](https://lapig-ufg.github.io/semente/llms.txt) and
  `/llms-full.txt`, handy if you prefer feeding the docs to a model directly.
