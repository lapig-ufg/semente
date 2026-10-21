# The Domain

A **domain** is everything domain-specific the framework needs to build your
assistant. It is a single `DomainSpec` instance exposed as `domain_spec` from
your `domain` module.

## `DomainSpec`

```python
from semente import load_skills
from semente.domain import DomainSpec

domain_spec = DomainSpec(
    name="My App",
    tools=get_tools,              # list | Callable[[Context], list]
    knowledge=kb,                 # engine-neutral Knowledge | None
    skills=load_skills("domain/skills"),  # Engine-neutral Skills | None
    instructions=get_instructions, # Callable[[Context], str] | None
    agent_config="single_agent",   # key into prompts/agents.yml
)
```

| Field | Type | Description |
|---|---|---|
| `name` | `str` | Human-readable app name. |
| `tools` | `list` or `Callable` | Tools handed to the single agent. A callable `(run_context) -> list` enables **dynamic tool selection** (e.g. different tools per registration state). |
| `knowledge` | `Knowledge \| None` | Optional vector KB; enables knowledge search for Q&A. Built engine-neutrally with `semente.knowledge.build_knowledge` / `build_search_tool`. |
| `skills` | `Skills \| None` | Optional skills package loaded with `semente.skills.load_skills` (SKILL.md packages) — engine-neutral, not an engine feature. |
| `instructions` | `Callable \| None` | Domain-specific dynamic instructions. When `None`, a generic builder (persona + context blocks + `instructions_default`) is used. |
| `agent_config` | `str` | Key into `prompts/agents.yml` selecting the agent's metadata/instructions. Defaults to `single_agent`. |
| `guardrails` | `list` | Optional pluggable input guardrails — redact sensitive spans or block the turn. See [Guardrails](guardrails.md). |

## Dynamic tools and instructions

The two callables are where domain logic lives. They receive the
`semente.context.Context` (a structural `Protocol` satisfied by the engine's
run context — no wrapping, no conversion) and read/write `session_state`.

```python
from semente.context import Context as RunContext

def get_tools(run_context: RunContext):
    state = run_context.session_state
    if state.get("registration_state") == "pending":
        return [confirm_selection, cancel]
    return [register, analyze, ask]

def get_instructions(run_context: RunContext) -> str:
    state = run_context.session_state
    if state.get("registration_state") == "pending":
        return "Ask the user to confirm the selected property."
    return "You are the assistant. Answer using your tools."
```

## Neutral helpers

Semente exposes two helpers the domain can reuse when building instructions:

```python
from semente.agents.build_agent import context_blocks, persona_text
```

- `context_blocks(session_state)` — the `<history_context>` and
  `<conversation_summary>` blocks maintained by the agent pipeline.
- `persona_text(session_state)` — the user's tracked persona, or the fallback.

## Example: the Echo domain

The minimal possible domain — one tool, nothing else:

```python
from semente import tool
from semente.domain import DomainSpec

@tool(description="Echo the given message back to the user.")
def echo(message: str) -> str:
    return f"Echo: {message}"

domain_spec = DomainSpec(name="Echo Domain", tools=[echo])
```

See `examples/minimal-chat/` in the repository — it also ships localized
prompt overrides (`domain/prompts/`).
