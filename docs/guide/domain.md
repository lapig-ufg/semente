# The Domain

A **domain** is everything domain-specific the framework needs to build your
assistant. It is a single `DomainSpec` instance exposed as `domain_spec` from
your `domain` module.

## `DomainSpec`

```python
from semente.domain import DomainSpec

domain_spec = DomainSpec(
    name="Pasto Legal",
    tools=get_tools,              # list[Any] | Callable[[RunContext], list]
    knowledge=pasto_legal_kb,     # Agno Knowledge | None
    skills=skills,                 # Agno Skills | None
    instructions=get_instructions, # Callable[[RunContext], str] | None
    agent_config="single_agent",   # key into prompts/agents.yml
)
```

| Field | Type | Description |
|---|---|---|
| `name` | `str` | Human-readable app name. |
| `tools` | `list` or `Callable` | Agno tools handed to the single agent. A callable `(run_context) -> list` enables **dynamic tool selection** (e.g. different tools per registration state). |
| `knowledge` | `Knowledge \| None` | Optional vector KB; enables `search_knowledge_base` for Q&A. |
| `skills` | `Skills \| None` | Optional Agno skills (markdown instructions loaded as skills). |
| `instructions` | `Callable \| None` | Domain-specific dynamic instructions. When `None`, a generic builder (persona + context blocks + `instructions_default`) is used. |
| `agent_config` | `str` | Key into `prompts/agents.yml` selecting the agent's metadata/instructions. Defaults to `single_agent`. |

## Dynamic tools and instructions

The two callables are where domain logic lives. They receive the Agno
`RunContext` and read/write `session_state`.

```python
from agno.run import RunContext

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
from agno.tools import tool
from semente.domain import DomainSpec

@tool(description="Echo the given message back to the user.")
def echo(message: str) -> str:
    return f"Echo: {message}"

domain_spec = DomainSpec(name="Echo Domain", tools=[echo])
```

See `examples/echo_domain/` in the repository.
