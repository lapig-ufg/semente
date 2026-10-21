# Architecture

Semente is a **domain-neutral harness**: a multi-agent chat pipeline the
framework assembles for you, plus three seams where your app plugs in — the
**domain** (`DomainSpec`), the **manifest** (`semente.yaml`), and the **engine
port** (swappable LLM backends).

```
your app                          Semente (the framework)
─────────                         ────────────────────────
domain/__init__.py  ──┐
semente.yaml        ──┼──►  Harness (turn pipeline) ──► engine backend
optional channels   ──┘        │                          (agno | adk | bare)
override prompts    ──        sub-agents, tools, DB, TTS, geo
```

## The turn pipeline (the Harness)

`Harness` (`semente/core/harness.py`) owns one user turn end-to-end. Every
channel (Streamlit, WhatsApp) calls the same `get_harness().run(...)`.

```
                      ┌─────────────────────────────┐
 message + session ──►│      input preprocessing    │
                      │  media→text · geo→GeoJSON   │
                      └──────────────┬──────────────┘
                                     ▼
                      ┌─────────────────────────────┐
                      │       PII guardrail         │
                      └──────────────┬──────────────┘
                                     ▼
                      ┌─────────────────────────────┐
              ┌── no  │       onboarding gate       │
              │       └──────────────┬──────────────┘
              │                      │ needed (terms/persona missing)
              │                      ▼
              │       ┌─────────────────────────────┐
              │       │      welcoming agent        │ staged onboarding,
              │       │   (terms → persona stages)  │ one stage per turn
              │       └──────────────┬──────────────┘
              │                      │
              ▼                      ▼
 ┌─────────────────────────────────────────────────────┐
 │  summarization (every 6 turns)                      │
 │  → feedback loop (satisfaction → persistence →      │
 │    persona)                                         │
 │  → remediation cycle open? yes: retry + apology     │
 │                            no:  main agent + tools  │
 └────────────────────────────┬────────────────────────┘
                              ▼
              ┌─────────────────────────────┐
              │      finalize output        │  TTS, persistence,
              └─────────────────────────────┘  pending history
```

Stages in order:

1. **Input preprocessing** — images and audio are converted to text by
   dedicated media agents (descriptions/transcriptions are PII-redacted
   inline); geo upload files (`.zip/.kmz/.kml/.geojson`, optional `geo` extra)
   are converted to a single GeoJSON `File` via
   `services/geospatial/geojson_io.py`.
2. **PII guardrail** (feature `pii_guardrail`) — LGPD/PII redaction of the
   user text before anything else sees it.
3. **Onboarding gate** — DB-backed check of terms acceptance and persona
   completeness. When needed, the **welcoming agent** takes over the turn and
   runs the staged onboarding flow (terms → persona), one stage per turn.
4. **Summarization** (feature `summarization`) — a rolling summary refreshed
   every 6 turns (`SUMMARY_THRESHOLD`).
5. **Feedback loop** (feature `feedback_workflow`) — a satisfaction agent
   evaluates the turn (`Effectiveness`: level 1–5 + `changed_topic`),
   persistence routes to the DPO/SFT branches, and a persona agent
   conditionally updates the user profile. A frustration *without* a topic
   change opens a **remediation cycle**, which overrides the main agent's
   output with an apology and injects a retry instruction. The separate
   `feedback` feature only gates SFT trajectory capture — see
   [Feedback & Fine-Tuning](/guide/feedback).
6. **Finalize output** — TTS synthesis (feature `tts`, Gemini TTS via
   `services/audio/tts.py`), then persistence: session state, run history, and
   the pending feedback history.

The main agent is built once per app: `_load_domain` imports your
`domain_spec`, `agents/build_agent.py` resolves its configuration from
`prompts/agents.yml`, injects skills, and hands the backend an `AgentSpec`.
Model fallback: a second, engine-agnostic `FallbackAgent` wraps the primary —
any exception from the primary triggers one retry with the fallback model.

## Package map

| Package | Responsibility |
|---|---|
| `semente/core/` | The `Harness` turn pipeline; engine-free types (`StepOutput`, `Session`, `SessionStore`) |
| `semente/agents/` | Agent factories: `build_agent`, welcoming, media, feedback, persona, summary |
| `semente/backends/` | The **engine port**: contract (`base.py`), registry, and the `agno`, `adk`, `bare` backends; `toolkit.py` is the engine-neutral tool-execution seam |
| `semente/interfaces/` | Channels: Streamlit webapp (+ debug panel), WhatsApp webhook router |
| `semente/configs/` | Env config factory, prompts/i18n loader, first-run wizard, logging |
| `semente/domain/` | The customization seam: `DomainSpec`, demo domain |
| `semente/hooks/` | Tool middleware (hooks) shipped with the framework |
| `semente/guardrails/` | PII/LGPD redaction (`pii_gate.py`) used by the guardrail stage and feedback persistence |
| `semente/tools/` | Native media/tool types, `@tool` decorator, `Calculator`, framework-owned tools (onboarding, persona, feedback, TTS shim, version) |
| `semente/database/` | SQLAlchemy session/records + models (users, feedback, sessions) |
| `semente/schemas/` | Pydantic state schemas (persona, interaction assessment, fine-tuning rows) |
| `semente/services/` | Plain services behind the agents: `audio/tts`, `geospatial/geojson_io`, `session_migration` |
| `semente/knowledge/` | Engine-neutral knowledge-base factory and search tool |
| `semente/skills.py` | Engine-neutral SKILL.md loader (`load_skills`) with three access tools |
| `semente/cli/` | The `semente` command: `init`, `config`, `status`, `launch` |
| `semente/build.py` | `build_app(manifest)` — the programmatic entry point |

## The engine port

A backend owns exactly three things — model construction, agent construction,
and the run primitive — and nothing else:

```python
class EngineBackend(ABC):
    def build_agent(self, spec: AgentSpec) -> Agent: ...
    def supports(self, capability: str) -> bool: ...

class Agent(Protocol):
    def run(self, input: AgentInput) -> AgentTurn: ...
```

- **`AgentSpec`** carries name, instructions callable, tools, output schema,
  model (`ModelSpec`), `multimodal_in`, knowledge, and skills.
- **`AgentInput`** is text + images/audio (media parts) + files (also injected
  into tools declaring a `files` parameter) + session state.
- **`AgentTurn`** is content + optional media + `structured` (schema output) +
  `usage` + `metrics`.

Everything else — orchestration, sessions, prompts, knowledge, skills,
guardrails, channels — is Semente-owned and engine-free. Tools cross the seam
through `backends/toolkit.py` (hook chain, context injection, media bag,
schema), so a tool written once runs identically on every backend.

Registry resolution (`backends/registry.py`): the manifest `engine` field →
the `SEMENTE_ENGINE` env var → `agno` default. See
[Engines](/guide/engines) for the backend list and capability matrix.

## Extension points

| You want to customize | How |
|---|---|
| Tools, knowledge, skills, persona, instructions | `DomainSpec` — see [The Domain](/guide/domain) |
| Agent instructions, tool description texts, language | `prompts/` YAML files — see [Prompts & i18n](/guide/prompts) |
| App-level options | `semente.yaml` — see [Manifest Reference](/guide/manifest) |
| Per-tool validation | `@tool(tool_hooks=[...])` middleware — see `semente/hooks/tool_hooks.py` |
| The LLM engine | implement `EngineBackend` in `semente/backends/<name>/` and register it — see [Engines](/guide/engines) |
| A new channel | implement a webhook/webapp that calls `get_harness().run()`, mount it in `semente/build.py` — see [Channels](/guide/channels) |

## Entry points

| Surface | What | Notes |
|---|---|---|
| `semente` CLI | `init`, `config`, `status`, `launch` | `launch streamlit` for the dev chat UI; `launch --demo` for the built-in demo agent |
| `build_app(manifest_path)` | FastAPI ASGI app | Mounts the WhatsApp webhook when `channels` includes `whatsapp`; run with `python main.py` |
| `get_harness(manifest_path)` | The live pipeline | What channels call; `manifest_path` resolves from the argument, `SEMENTE_MANIFEST`, then `./semente.yaml` |