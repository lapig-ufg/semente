# Engines

A engine do Semente é intercambiável. A engine move o laço do LLM (chat +
chamada de ferramentas + saída estruturada); todo o resto — orquestração,
sessões, conhecimento, skills, guardrails, canais — pertence ao Semente e é
livre de engine.

## Selecionando uma engine

```yaml
# semente.yaml
engine: adk          # agno (padrão) | adk | bare
```

Ou por variável de ambiente:

```bash
export SEMENTE_ENGINE=adk
```

Ordem de resolução: um campo `engine` explícito no manifesto vence; a variável
de ambiente vale quando o manifesto não define uma; o padrão é `agno`. A engine
escolhida se aplica a **todos** os agentes do app — o principal e todos os
subagentes (boas-vindas, persona, feedback, sumarização, mídia) — não só o
principal.

O mesmo domínio, manifesto, prompts e canais rodam sem alterações.

## Backends

| Engine | Nível | Runtime | Observações |
|---|---|---|---|
| **agno** | Estável | Python, em processo | Implementação de referência |
| **adk** | Suportado | Python, em processo | Google Agent Development Kit |
| **bare** | Suportado | Python, em processo | Sem framework — nosso próprio laço de ferramentas sobre a porta de provedores |

## O contrato

Cada backend implementa `semente.backends.base.EngineBackend`:

```python
class EngineBackend(ABC):
    def build_agent(self, spec: AgentSpec) -> Agent: ...
    def supports(self, capability: str) -> bool: ...
```

O `AgentSpec` carrega o nome, o callable de instruções, as ferramentas, o schema
de saída, o modelo, o conhecimento e as skills. `Agent.run(AgentInput) ->
AgentTurn` é a única primitiva de execução.

## Fallback de modelo

Toda engine ganha uma rede de segurança no nível do modelo: configure um modelo
de fallback e o Semente tenta uma vez com ele quando o primário falha (limites de
taxa, indisponibilidade do modelo).

```yaml
# semente.yaml
models:
  primary: { provider: google, id: gemini-3.5-flash-lite }
  fallback: { provider: ollama, id: gemma4:31b-cloud }
```

Ou pelas variáveis de ambiente `FALLBACK_MODEL_PROVIDER` / `FALLBACK_MODEL_ID`. A
nova tentativa é agnóstica de engine (`FallbackAgent` envolve quaisquer duas
instâncias de `Agent`).

## Matriz de capacidades

| Capacidade | agno | adk | bare |
|---|---|---|---|
| Chamada de ferramentas | ✓ | ✓ | ✓ |
| Saída estruturada | ✓ | ✓ | planejado |
| Entrada multimodal | ✓ | ✓ (imagens/áudio) | ✓ (imagens/áudio/arquivos) |
| Saída de mídia | ✓ | ✓ | ✓ |
| Estado da sessão nas ferramentas | ✓ | ✓ (tool_context) | ✓ (StateContext) |
| Conhecimento (busca na KB) | ✓ | ✓ (A-K) | planejado (A-K) |
| Tool hooks | ✓ | ✓ (A-H) | ✓ (A-H) |
| Skills | ✓ | ✓ (A-S) | ✓ (A-S) |
| Fallback de modelo | ✓ | ✓ | ✓ (modelos Google) |

## O backend bare

A engine `bare` é o estado final da porta de engine: quando mídia (A-M), hooks
(A-H), conhecimento (A-K) e skills (A-S) vivem no Semente, uma engine só precisa
executar o laço do LLM. `semente/backends/bare/` faz isso com nossos próprios
agentes — sem framework, sem litellm:

- `MyAgent` (`agent.py`) conduz o chat e a chamada de ferramentas pela porta de
  provedores (`providers/`): as `Tool`s do semente viram `FunctionDeclaration`s
  tipadas, a execução de ferramentas é neutra quanto à engine
  (`backends/toolkit.py` — hooks, run_context, bolsa de mídia), e o turno do
  modelo é devolvido preservando as thought signatures do Gemini 3. Primeiro
  provedor: Gemini via `google-genai`.

O `BareBackend.build_agent` encaminha toda spec ao `MyAgent`. Ainda não
implementados (planejados, veja `semente/backends/bare/DECISIONS.md`): saída
estruturada (`AgentTurn.structured` permanece `None` — os ciclos de
feedback/persona degradam com elegância) e busca na base de conhecimento. Para
essas capacidades hoje, use a engine `agno` ou `adk`.

O `MyAgent` é multimodal: `AgentInput.images`/`audio`/`files` vão todos ao
modelo como partes de transmissão no turno do usuário da primeira rodada, e
`files` também entram nas ferramentas que declaram um parâmetro `files` (a
convenção do framework). `run(AgentInput)` é o único ponto de entrada.

O `MyAgent` também tem um sistema de eventos — `agent.subscribe(AgentEvents.X,
handler)` observa ou customiza execuções: `AGENT_START` (estado da sessão, por
referência) e `AGENT_END` (o log de mensagens da execução) nas fronteiras da
execução, `TOOL_EXECUTION_START` e `TOOL_EXECUTION_END` em torno de cada
execução de ferramenta. Os handlers recebem um único objeto de evento mutável —
atribua `tool_name`/`args` no evento de início para redirecionar o que executa:

```python
from semente.backends.bare import AgentEvents

agent.subscribe(
    AgentEvents.TOOL_EXECUTION_START,
    lambda e: e.args.update(feature_id="f2"),  # observa ou altera
)
```

Toda execução do `MyAgent` também retorna métricas em `AgentTurn.metrics` —
contagem de tokens direto do provedor (entrada/saída/total/raciocínio/leitura de
cache, acumulados), tempos por rodada e por ferramenta, e a contagem de rodadas
do provedor.

O `MyAgent` também aceita skills nativamente: `skills=` recebe um objeto
`Skills` ou um callable `(run_context) -> Skills | None` resolvido contra o
estado da execução — o mesmo padrão de `instructions` e `tools`. Construa as
`Skills` você mesmo com `load_skills` (um diretório ou uma lista deles); toda
execução injeta as instruções `<skills_system>` mais as três ferramentas de
acesso a skills:

```python
from semente.backends.bare import MyAgent
from semente.skills import load_skills

skills = load_skills("domain/skills")           # construção no lado do chamador
agent = MyAgent(instructions="...", tools=[...],
                skills=lambda ctx: skills if ctx.session_state.get("pro") else None)
```

## Conhecimento: agno como biblioteca

A *recuperação* de conhecimento é neutra quanto à engine (`build_search_tool`
retorna uma função simples que todo backend adapta). A pilha de *armazenamento*
— embedder, chunking, PgVector/ChromaDb — continua sendo classes do agno, usadas
como biblioteca de banco vetorial e não como engine de agentes; a fábrica de
conhecimento em `semente/knowledge/` mantém isso atrás de uma API neutra
(ingestão de markdown, sincronização por hash de conteúdo). A remoção completa do
agno do armazenamento fica adiada até que uma implantação sem agno precise dela.

## Escrevendo um backend

Implemente o `EngineBackend` em `semente/backends/<name>/` e registre-o em
`semente/backends/registry.py`. Veja `semente/backends/agno/` como referência e
`semente/backends/toolkit.py` para a costura compartilhada de execução de
ferramentas (bolsa de mídia, cadeia de hooks, schema).
