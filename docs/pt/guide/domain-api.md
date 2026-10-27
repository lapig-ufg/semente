# API do Domínio

A **API do Domínio** é a superfície estável da qual um app Semente importa. Ela
é **livre de engine**: um domínio nunca importa o framework de agentes
subjacente (Agno). O Semente é o único módulo que toca a engine.

## Imports

```python
from semente import tool, ToolResult, Image, Video, File, Audio, Calculator
from semente.context import Context as RunContext
from semente.logging import log_debug, log_info, log_warning, log_error
from semente.knowledge import Knowledge, GeminiEmbedder, PgVector, ChromaDb, RecursiveChunking, Distance
from semente.skills import load_skills
from semente.domain import DomainSpec
```

## `tool` — declarar uma ferramenta

```python
from semente import tool

@tool(description="Devolve a mensagem recebida ao usuário.")
def echo(message: str) -> str:
    return f"Echo: {message}"
```

Aceita os mesmos kwargs do decorador da engine (`description=`,
`tool_hooks=`). As descrições das ferramentas podem vir do carregador de prompts:

```python
from semente.configs.prompts import get_tool_description

@tool(description=get_tool_description("weather_tools", "get_temperature_forecast"))
def get_temperature_forecast(run_context: RunContext, feature_id: str) -> ToolResult:
    ...
```

## `Context` — o contexto de execução

Um Protocol estrutural. A engine injeta seu próprio objeto de contexto, que o
satisfaz por duck typing — sem encapsulamento, sem custo de conversão.

```python
from semente.context import Context as RunContext

def get_tools(run_context: RunContext):
    state = run_context.session_state
    ...
```

Atributos disponíveis: `session_state`, `user_id`, `messages`.

## `ToolResult` e tipos de mídia

```python
from semente import ToolResult, Image, Video, File, Audio

return ToolResult(
    content="Mapa gerado",
    images=[Image(content=png_bytes)],
    videos=[Video(content=mp4_bytes, mime_type="video/mp4", format="mp4")],
    files=[File(content=pdf_bytes, mime_type="application/pdf")],
)
```

## `load_skills`

```python
from semente.skills import load_skills

skills = load_skills("domain/skills/my_skill")  # None se inválida/ausente
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

## A garantia

O `scripts/check_domain_purity.sh` faz o CI falhar se qualquer módulo de
`domain/` ou `examples/` importar a engine diretamente:

```bash
./scripts/check_domain_purity.sh   # ✓ domain is engine-free
```

O nível 1 da abstração está completo: `tools`, contexto, mídia, conhecimento e
skills são todos neutros quanto à engine (tipos nativos ou funções simples que
cada backend adapta). O que difere entre as engines hoje é interno a cada
backend — veja [Engines](engines.md) para a matriz de capacidades e
`semente/backends/bare/DECISIONS.md` para o registro de design do backend `bare`,
livre de framework.
