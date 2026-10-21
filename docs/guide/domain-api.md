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

Level 1 of the abstraction is complete: `tools`, context, media, knowledge,
and skills are all engine-neutral (native types or plain functions every
backend adapts). What differs between engines today is internal to each
backend — see [Engines](engines.md) for the capability matrix and
`semente/backends/bare/DECISIONS.md` for the design record behind the
framework-free `bare` backend.
