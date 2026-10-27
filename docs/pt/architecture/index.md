# Arquitetura

O Semente é um **harness neutro quanto ao domínio**: um pipeline de chat
multiagente que o framework monta para você, mais três pontos de encaixe onde o
seu app se conecta — o **domínio** (`DomainSpec`), o **manifesto**
(`semente.yaml`) e a **porta de engine** (backends de LLM intercambiáveis).

```
seu app                           Semente (o framework)
─────────                          ────────────────────────
domain/__init__.py  ──┐
semente.yaml        ──┼──►  Harness (pipeline de turno) ──► backend de engine
canais opcionais    ──┘        │                          (agno | adk | bare)
prompts sobrescritos ──        subagentes, ferramentas, BD, TTS, geo
```

## O pipeline de turno (o Harness)

O `Harness` (`semente/core/harness.py`) é dono de um turno do usuário de ponta a
ponta. Todo canal (Streamlit, WhatsApp) chama o mesmo `get_harness().run(...)`.

```
                      ┌─────────────────────────────┐
 mensagem + sessão ──►│   pré-processamento entrada │
                      │  mídia→texto · geo→GeoJSON  │
                      └──────────────┬──────────────┘
                                     ▼
                      ┌─────────────────────────────┐
                      │ cadeia de guardrails        │  ocultação, ou um
                      │ (plugável)                  │  turno bloqueado
                      └──────────────┬──────────────┘
                                     ▼
                      ┌─────────────────────────────┐
              ┌── não │     portão de onboarding    │
              │       └──────────────┬──────────────┘
              │                      │ necessário (termos/persona ausentes)
              │                      ▼
              │       ┌─────────────────────────────┐
              │       │   agente de boas-vindas     │ onboarding em etapas,
              │       │ (etapas termos → persona)   │ uma etapa por turno
              │       └──────────────┬──────────────┘
              │                      │
              ▼                      ▼
 ┌─────────────────────────────────────────────────────┐
 │  sumarização (a cada 6 turnos)                      │
 │  → avaliação da interação (satisfação → persistência│
 │    → persona)                                       │
 │  → ciclo de remediação aberto? sim: nova tentativa  │
 │    + desculpas                                      │
 │                          não: agente principal      │
 │                               + ferramentas         │
 └────────────────────────────┬────────────────────────┘
                              ▼
              ┌─────────────────────────────┐
              │     finalizar saída         │  TTS, persistência,
              └─────────────────────────────┘  histórico pendente
```

Etapas, em ordem:

1. **Pré-processamento da entrada** — imagens e áudio são convertidos em texto
   por agentes de mídia dedicados (descrições/transcrições têm PII ocultada
   in-line); arquivos geo enviados (`.zip/.kmz/.kml/.geojson`, extra opcional
   `geo`) são convertidos em um único `File` GeoJSON por
   `services/geospatial/geojson_io.py`.
2. **Cadeia de guardrails** (feature `guardrails`, plugável) — os
   `DomainSpec.guardrails` do app rodam na ordem da lista sobre a entrada: cada
   guard oculta trechos sensíveis (`EmailGuardrail`/`CardGuardrail` universais
   vêm como builtins opt-in) ou **bloqueia o turno** com uma resposta ao usuário
   (o agente nunca executa). O texto derivado de mídia (etapa 1) e a persistência
   DPO/SFT são sanitizados pela mesma cadeia; as portas dos canais (`MessageContent`
   do WhatsApp, Streamlit) também ocultam por ela. Um app sem guardrails
   declarados não oculta nada — a privacidade é guiada por declaração.
3. **Portão de onboarding** — verificação, no BD, da completude da persona e,
   quando a feature `terms-acceptance` está habilitada, do aceite dos termos.
   Quando necessário, o **agente de boas-vindas** assume o turno e executa o
   fluxo de onboarding em etapas (termos → persona, ou só persona), uma etapa por
   turno.
4. **Sumarização** (feature `summarization`) — um resumo contínuo atualizado a
   cada 6 turnos (`SUMMARY_THRESHOLD`).
5. **Avaliação da interação** (feature `interaction-assessment`) — o ciclo por
   turno: um agente de satisfação avalia o turno (`Effectiveness`: nível 1–5 +
   `changed_topic`), a persistência encaminha para os ramos DPO/SFT (a opção
   aninhada `window_size` controla a janela de trajetória SFT) e um agente de
   persona atualiza condicionalmente o perfil do usuário. Uma frustração *sem*
   mudança de tópico abre um **ciclo de remediação**, que sobrescreve a saída do
   agente principal com um pedido de desculpas e injeta uma instrução de nova
   tentativa — veja [Feedback e Fine-Tuning](/pt/guide/feedback).
6. **Finalizar a saída** — síntese TTS (feature `tts`, Gemini TTS via
   `services/audio/tts.py`), depois persistência: estado da sessão, histórico de
   execuções e o histórico de feedback pendente.

O agente principal é construído uma vez por app: `_load_domain` importa o seu
`domain_spec`, `agents/build_agent.py` resolve a configuração a partir de
`prompts/agents.yml`, injeta skills e entrega ao backend um `AgentSpec`.
Fallback de modelo: um segundo `FallbackAgent`, agnóstico de engine, envolve o
primário — qualquer exceção do primário dispara uma nova tentativa com o modelo
de fallback.

## Mapa de pacotes

| Pacote | Responsabilidade |
|---|---|
| `semente/core/` | O pipeline de turno `Harness`; tipos livres de engine (`StepOutput`, `Session`, `SessionStore`) |
| `semente/agents/` | Fábricas de agentes: `build_agent`, boas-vindas, mídia, feedback, persona, resumo |
| `semente/backends/` | A **porta de engine**: contrato (`base.py`), registro e os backends `agno`, `adk`, `bare`; `toolkit.py` é a costura neutra de execução de ferramentas |
| `semente/interfaces/` | Canais: webapp Streamlit (+ painel de depuração), roteador de webhook do WhatsApp |
| `semente/configs/` | Fábrica de config de ambiente, carregador de prompts/i18n, assistente da primeira execução, logging |
| `semente/domain/` | O ponto de customização: `DomainSpec`, domínio de demonstração |
| `semente/hooks/` | Middleware de ferramentas (hooks) que acompanha o framework |
| `semente/guardrails/` | A **interface plugável de guardrails de entrada**: contrato + cadeia (`base.py`), builtins universais (`builtin.py`); detectores específicos de país vão no domínio |
| `semente/tools/` | Tipos nativos de mídia/ferramentas, decorador `@tool`, `Calculator`, ferramentas do framework (onboarding, persona, feedback, shim de TTS, versão) |
| `semente/database/` | Sessão/registros SQLAlchemy + modelos (usuários, feedback, sessões) |
| `semente/schemas/` | Schemas de estado Pydantic (persona, avaliação da interação, linhas de fine-tuning) |
| `semente/services/` | Serviços simples por trás dos agentes: `audio/tts`, `geospatial/geojson_io`, `session_migration` |
| `semente/knowledge/` | Fábrica de base de conhecimento neutra quanto à engine e ferramenta de busca |
| `semente/skills.py` | Carregador SKILL.md neutro quanto à engine (`load_skills`) com três ferramentas de acesso |
| `semente/cli/` | O comando `semente`: `init`, `config`, `status`, `launch` |
| `semente/build.py` | `build_app(manifest)` — o ponto de entrada programático |

## A porta de engine

Um backend é dono de exatamente três coisas — construção do modelo, construção do
agente e a primitiva de execução — e nada além disso:

```python
class EngineBackend(ABC):
    def build_agent(self, spec: AgentSpec) -> Agent: ...
    def supports(self, capability: str) -> bool: ...

class Agent(Protocol):
    def run(self, input: AgentInput) -> AgentTurn: ...
```

- **`AgentSpec`** carrega nome, callable de instruções, ferramentas, schema de
  saída, modelo (`ModelSpec`), `multimodal_in`, conhecimento e skills.
- **`AgentInput`** é texto + imagens/áudio (partes de mídia) + arquivos (também
  injetados em ferramentas que declaram um parâmetro `files`) + estado da sessão.
- **`AgentTurn`** é conteúdo + mídia opcional + `structured` (saída por schema) +
  `usage` + `metrics`.

Todo o resto — orquestração, sessões, prompts, conhecimento, skills, guardrails,
canais — pertence ao Semente e é livre de engine. As ferramentas cruzam a
costura por `backends/toolkit.py` (cadeia de hooks, injeção de contexto, bolsa de
mídia, schema), de modo que uma ferramenta escrita uma vez roda de forma idêntica
em todo backend.

Resolução do registro (`backends/registry.py`): o campo `engine` do manifesto →
a variável de ambiente `SEMENTE_ENGINE` → padrão `agno`. Veja
[Engines](/pt/guide/engines) para a lista de backends e a matriz de capacidades.

## Pontos de extensão

| Você quer customizar | Como |
|---|---|
| Ferramentas, conhecimento, skills, persona, instruções | `DomainSpec` — veja [O Domínio](/pt/guide/domain) |
| Segurança de entrada (ocultação/bloqueio) | `DomainSpec.guardrails` — veja [Guardrails](/pt/guide/guardrails) |
| Instruções dos agentes, textos de descrição de ferramentas, idioma | arquivos YAML em `prompts/` — veja [Prompts e i18n](/pt/guide/prompts) |
| Opções em nível de app | `semente.yaml` — veja [Referência do Manifesto](/pt/guide/manifest) |
| Validação por ferramenta | middleware `@tool(tool_hooks=[...])` — veja `semente/hooks/tool_hooks.py` |
| A engine de LLM | implemente `EngineBackend` em `semente/backends/<name>/` e registre-o — veja [Engines](/pt/guide/engines) |
| Um novo canal | implemente um webhook/webapp que chame `get_harness().run()` e monte-o em `semente/build.py` — veja [Canais](/pt/guide/channels) |

## Pontos de entrada

| Superfície | O quê | Observações |
|---|---|---|
| CLI `semente` | `init`, `config`, `status`, `launch` | `launch streamlit` para a interface de chat de desenvolvimento; `launch --demo` para o agente de demonstração embutido |
| `build_app(manifest_path)` | App ASGI FastAPI | Monta o webhook do WhatsApp quando `channels` inclui `whatsapp`; execute com `python main.py` |
| `get_harness(manifest_path)` | O pipeline ativo | O que os canais chamam; o `manifest_path` é resolvido a partir do argumento, de `SEMENTE_MANIFEST` e depois de `./semente.yaml` |
