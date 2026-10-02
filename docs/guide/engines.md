# Engines

Semente's engine is swappable. The engine powers the LLM loop (chat + tool
calling + structured output); everything else — orchestration, sessions,
knowledge, skills, guardrails, channels — is Semente-owned and engine-free.

## Selecting an engine

```yaml
# semente.yaml
engine: adk          # agno (default) | adk | bare
```

Or via environment variable:

```bash
export SEMENTE_ENGINE=adk
```

Resolution order: an explicit manifest `engine` field wins; the env var
applies when the manifest doesn't set one; the default is `agno`. The chosen
engine applies to **every** agent in the app — the main agent and all
sub-agents (welcoming, persona, feedback, summarization, media) — not just
the main one.

The same domain, manifest, prompts, and channels run unchanged.

## Backends

| Engine | Tier | Runtime | Notes |
|---|---|---|---|
| **agno** | Stable | Python, in-process | Reference implementation |
| **adk** | Supported | Python, in-process | Google Agent Development Kit |
| **bare** | Supported | Python, in-process | No framework — our own tool loop over the provider port |

## The contract

Each backend implements `semente.backends.base.EngineBackend`:

```python
class EngineBackend(ABC):
    def build_agent(self, spec: AgentSpec) -> Agent: ...
    def supports(self, capability: str) -> bool: ...
```

`AgentSpec` carries the name, instructions callable, tools, output schema,
model, knowledge, and skills. `Agent.run(AgentInput) -> AgentTurn` is the
single run primitive.

## Model fallback

Every engine gets a model-level safety net: configure a fallback model and
Semente retries once with it when the primary fails (rate limits, model
unavailability).

```yaml
# semente.yaml
models:
  primary: { provider: google, id: gemini-3.5-flash-lite }
  fallback: { provider: ollama, id: gemma4:31b-cloud }
```

Or via `FALLBACK_MODEL_PROVIDER` / `FALLBACK_MODEL_ID` env vars. The retry is
engine-agnostic (`FallbackAgent` wraps any two `Agent` instances).

## Capability matrix

| Capability | agno | adk | bare |
|---|---|---|---|
| Tool calling | ✓ | ✓ | ✓ |
| Structured output | ✓ | ✓ | planned |
| Multimodal input | ✓ | ✓ (images/audio) | planned |
| Media output | ✓ | ✓ | ✓ |
| Session state in tools | ✓ | ✓ (tool_context) | ✓ (StateContext) |
| Knowledge (KB search) | ✓ | ✓ (A-K) | planned (A-K) |
| Tool hooks | ✓ | ✓ (A-H) | ✓ (A-H) |
| Skills | ✓ | ✓ (A-S) | ✓ (A-S) |
| Model fallback | ✓ | ✓ | ✓ (Google models) |

## The bare backend

The `bare` engine is the end state of the engine port: once media (A-M),
hooks (A-H), knowledge (A-K) and skills (A-S) live in Semente, an engine only
has to run the LLM loop. `semente/backends/bare/` does that with our own
agents — no framework, no litellm:

- `MyAgent` (`agent.py`) drives chat and tool calling over the provider port
  (`providers/`): semente `Tool`s become typed `FunctionDeclaration`s, tool
  execution is engine-neutral (`backends/toolkit.py` — hooks, run_context,
  media bag), and the model's turn is echoed back preserving Gemini 3
  thought signatures. First provider: Gemini over `google-genai`.

`BareBackend.build_agent` routes every spec to `MyAgent`. Not yet implemented
(planned, see `semente/backends/bare/DECISIONS.md`): structured output
(`AgentTurn.structured` stays `None` — the feedback/persona loops degrade
gracefully), multimodal input, knowledge-base search, and non-Google
providers. For those capabilities today, use the `agno` or `adk` engine.

## Knowledge: agno as a library

Knowledge *retrieval* is engine-neutral (`build_search_tool` returns a plain
function every backend adapts). The *storage* stack — embedder, chunking,
PgVector/ChromaDb — remains agno classes, used as a vector-DB library rather
than the agent engine. Full de-agno of storage is deferred until a non-agno
deployment needs it (see `AGNOSTIC_PENDING.md`).

## Writing a backend

Implement `EngineBackend` in `semente/backends/<name>/` and register it in
`semente/backends/registry.py`. See `semente/backends/agno/` as the reference
and `semente/backends/toolkit.py` for the shared tool-execution seam (media
bag, hook chain, schema).
