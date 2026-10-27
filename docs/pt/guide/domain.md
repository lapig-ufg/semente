# O Domínio

Um **domínio** é tudo o que é específico da área e que o framework precisa para
construir o seu assistente. É uma única instância de `DomainSpec` exposta como
`domain_spec` pelo seu módulo `domain`.

## `DomainSpec`

```python
from semente import load_skills
from semente.domain import DomainSpec

domain_spec = DomainSpec(
    name="My App",
    tools=get_tools,              # list | Callable[[Context], list]
    knowledge=kb,                 # Knowledge neutro quanto à engine | None
    skills=load_skills("domain/skills"),  # Skills neutras quanto à engine | None
    instructions=get_instructions, # Callable[[Context], str] | None
    agent_config="single_agent",   # chave em prompts/agents.yml
)
```

| Campo | Tipo | Descrição |
|---|---|---|
| `name` | `str` | Nome legível do app. |
| `tools` | `list` ou `Callable` | Ferramentas entregues ao agente único. Um callable `(run_context) -> list` habilita a **seleção dinâmica de ferramentas** (ex.: ferramentas diferentes conforme o estado de cadastro). |
| `knowledge` | `Knowledge \| None` | KB vetorial opcional; habilita a busca de conhecimento para perguntas e respostas. Construída de forma neutra com `semente.knowledge.build_knowledge` / `build_search_tool`. |
| `skills` | `Skills \| None` | Pacote opcional de skills carregado com `semente.skills.load_skills` (pacotes SKILL.md) — neutro quanto à engine, não é um recurso da engine. |
| `instructions` | `Callable \| None` | Instruções dinâmicas específicas do domínio. Com `None`, usa-se um construtor genérico (persona + blocos de contexto + `instructions_default`). |
| `agent_config` | `str` | Chave em `prompts/agents.yml` que seleciona os metadados/instruções do agente. Padrão: `single_agent`. |
| `guardrails` | `list` | Guardrails de entrada plugáveis opcionais — ocultam trechos sensíveis ou bloqueiam o turno. Veja [Guardrails](guardrails.md). |

## Ferramentas e instruções dinâmicas

Os dois callables são onde mora a lógica do domínio. Eles recebem o
`semente.context.Context` (um `Protocol` estrutural satisfeito pelo contexto de
execução da engine — sem encapsulamento, sem conversão) e leem/escrevem
`session_state`.

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
        return "Peça ao usuário que confirme a propriedade selecionada."
    return "Você é o assistente. Responda usando suas ferramentas."
```

## Helpers neutros

O Semente expõe dois helpers que o domínio pode reutilizar ao montar instruções:

```python
from semente.agents.build_agent import context_blocks, persona_text
```

- `context_blocks(session_state)` — os blocos `<history_context>` e
  `<conversation_summary>` mantidos pelo pipeline de agentes.
- `persona_text(session_state)` — a persona rastreada do usuário, ou o fallback.

## Exemplo: o domínio Echo

O menor domínio possível — uma ferramenta, mais nada:

```python
from semente import tool
from semente.domain import DomainSpec

@tool(description="Devolve a mensagem recebida ao usuário.")
def echo(message: str) -> str:
    return f"Echo: {message}"

domain_spec = DomainSpec(name="Echo Domain", tools=[echo])
```

Veja `examples/minimal-chat/` no repositório — ele também traz sobrescritas de
prompts localizadas (`domain/prompts/`).
