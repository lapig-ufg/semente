# Domain API

The **Domain API** is the stable surface a Semente app imports from. It is
**engine-free**: a domain never imports the underlying agent framework (Agno).
Semente is the only module that touches the engine.

## Imports

```python
from semente import tool, ToolResult, Image, Video, File, Audio, Calculator
from semente.context import Context as RunContext
from semente.logging import log_debug, log_info, log_warning, log_error
from semente.knowledge import Knowledge, GeminiEmbedder, PgVector, ChromaDb, RecursiveChunking, Distance
from semente.skills import load_skills
from semente.domain import DomainSpec
```

## `tool` — declare a tool

```python
from semente import tool

@tool(description="Echo the given message back to the user.")
def echo(message: str) -> str:
    return f"Echo: {message}"
```

Supports the same kwargs as the engine's decorator (`description=`,
`tool_hooks=`). Tool descriptions can come from the prompts loader:

```python
from semente.configs.prompts import get_tool_description

@tool(description=get_tool_description("weather_tools", "get_temperature_forecast"))
def get_temperature_forecast(run_context: RunContext, feature_id: str) -> ToolResult:
    ...
```

## `Context` — the run context

A structural Protocol. The engine injects its own context object, which
satisfies it by duck typing — no wrapping, no conversion cost.

```python
from semente.context import Context as RunContext

def get_tools(run_context: RunContext):
    state = run_context.session_state
    ...
```

Available attributes: `session_state`, `user_id`, `messages`.

## `ToolResult` and media types

```python
from semente import ToolResult, Image, Video, File, Audio

return ToolResult(
    content="Map generated",
    images=[Image(content=png_bytes)],
    videos=[Video(content=mp4_bytes, mime_type="video/mp4", format="mp4")],
    files=[File(content=pdf_bytes, mime_type="application/pdf")],
)
```

## `load_skills`

```python
from semente.skills import load_skills

skills = load_skills("domain/skills/my_skill")  # None if invalid/absent
```

## `Tutorial` — declare the guided tutorial

A domain may ship a guided tutorial by supplying `get_tutorial` on the
`DomainSpec`: a factory returning a :class:`Tutorial` — the step count,
each step's teaching, its forward condition and its completion condition.
When it is absent (or `features.tutorial` is false in the manifest), the
feature is fully off: no offer, no supervisor, no checkpoint.

```python
from semente.domain import DomainSpec, Tutorial, TutorialStep

def get_tutorial() -> Tutorial:
    return Tutorial(
        steps=[
            TutorialStep(
                id="registration",
                lesson="…what this step teaches and the action to take…",
                forward_condition="…what counts as doing the step…",
                complete_condition="…what in the conversation proves it concluded…",
                # OR a callable: judged without any LLM call —
                # complete_condition=lambda session_state, user_text,
                #     agent_reply: bool(session_state.get("my_result")),
            ),
            TutorialStep(
                id="analyses",
                lesson="…",
                forward_condition="…",
                complete_condition="…",
            ),
        ],
        offer=None,    # optional custom ask for the welcoming agent
        closing=None,  # optional final message after the last step
        abandon=None,  # optional leave-early reply
    )

domain_spec = DomainSpec(
    name="My App",
    tools=[...],
    get_tutorial=get_tutorial,
)
```

The framework owns the machinery:

- **Supervisor** (contract in `prompts/agents.yml` under `tutorial_agent`) —
  grades every user message against the current step's `forward_condition`
  (forward to the real assistant) or teaches (`lesson`).
- **Checkpoint** (`tutorial_check_agent` in `agents.yml`) — after every
  forwarded turn, a `str` `complete_condition` is judged from the
  conversation and the real assistant's reply (structured verdict,
  fail-closed); a callable `complete_condition(session_state, user_text,
  agent_reply)` is executed by the pipeline directly.
- **Advancing** — when the condition is met, the step advances and the
  framework appends the congrats plus the NEXT step's `lesson` (or the
  `closing`) to the same reply; the last step closes the tutorial for good.

The fastest way to seed the example is the CLI:
`semente config enable tutorial` plants a working `domain/tutorial.py` and
wires `get_tutorial=get_tutorial` into your `DomainSpec` (when it can do so
safely; it always prints what it did).

## `Calculator`

```python
from semente import Calculator

Calculator(exclude_tools=["is_prime", "factorial"])
```

## Logging

```python
from semente.logging import log_debug, log_info, log_warning, log_error
```

## The guarantee

`scripts/check_domain_purity.sh` fails CI if any `domain/` or `examples/`
module imports the engine directly:

```bash
./scripts/check_domain_purity.sh   # ✓ domain is engine-free
```

See `ENGINE_ABSTRACTION.md` for the full abstraction roadmap (Level 1 is
implemented; Level 2 — native types + adapters — is planned).
