# Referência do Manifesto

O manifesto (`semente.yaml`) é a configuração em nível de app. Todo campo é
opcional, exceto `name` e `domain_module`.

```yaml
name: my-app                 # nome do app
language: pt-BR              # opcional; carrega prompts/<lang>/ se existir
domain_module: domain        # caminho de import que expõe `domain_spec`
prompts_dir: domain/prompts  # opcional; diretório de prompts explícito (sobrescreve language)
engine: agno                 # agno (padrão) | adk | bare
channels: [streamlit]        # streamlit e/ou whatsapp
features:                    # booleanos valem true por padrão (terms-acceptance: false)
  onboarding: true           # etapa de boas-vindas + nome/função antes do agente principal; false = responde direto
  tts: true                  # anexa a ferramenta TTS ao agente de boas-vindas
  interaction-assessment: true  # ciclo de satisfação/persona + captura DPO/SFT, ou {enable: true, window_size: 5}
  summarization: true        # resumo contínuo da conversa
  guardrails: true           # guardrails de entrada plugáveis (DomainSpec.guardrails)
  terms-acceptance:          # portão de termos no onboarding — desligado se não habilitado
    enable: true
    file: domain/terms.md    # texto de referência dos termos (obrigatório se habilitado)
    url: https://example.com/terms  # opcional: link enviado na primeira mensagem
models:                      # sobrescrita opcional da configuração de modelo por variáveis de ambiente
  primary: { provider: google, id: gemini-3.5-flash-lite }
  fallback: { provider: ollama, id: gemma4:31b-cloud }
```

## Campos

| Campo | Tipo | Padrão | Descrição |
|---|---|---|---|
| `name` | `str` | — | Nome do app; formatado nos prompts de onboarding e exibido no `semente status`. |
| `language` | `str` | `en` | Seleciona `prompts/<language>/` quando existe. |
| `domain_module` | `str` | `domain` | Caminho de import do módulo que expõe `domain_spec`. |
| `prompts_dir` | `str` | — | Diretório de prompts explícito (relativo ao cwd). Sobrescreve `language`. |
| `engine` | `str` | `agno` | Engine de agentes: `agno`, `adk` ou `bare`. Veja [Engines](engines.md). |
| `channels` | `list` | `[streamlit]` | `streamlit` e/ou `whatsapp`. |
| `features` | `dict` | todas `true` (exceto `terms-acceptance`) | Interruptores de features (veja abaixo). |
| `models` | `dict` | — | Sobrescreve a configuração de modelo do `.env`. |

## Resolução da engine

O campo `engine` do manifesto é o primeiro resolvedor. Quando ausente, o Semente
recorre à variável de ambiente `SEMENTE_ENGINE` e depois ao padrão `agno`:

```bash
export SEMENTE_ENGINE=adk    # vale quando o manifesto não tem o campo engine
```

## Interruptores de features

| Interruptor | Quando desligado |
|---|---|
| `onboarding` | Todo o portão de onboarding (termos + nome/função) é ignorado: cada turno vai direto ao agente principal, mesmo para um usuário novo e anônimo. Pensado para bots de propósito único como o [Groot](/pt/showcase/groot). Ligado por padrão. |
| `tts` | O agente de boas-vindas é construído sem a ferramenta TTS. |
| `interaction-assessment` | Todo o ciclo — agente de satisfação, persistência e captura DPO/SFT, atualizações de persona e remediação — é omitido da execução. Booleano ou `{enable, window_size}` — veja [Feedback e Fine-Tuning](feedback.md). |
| `summarization` | A etapa de resumo contínuo da conversa é omitida. |
| `guardrails` | A cadeia de guardrails do app (`DomainSpec.guardrails`) é ignorada em todo lugar — veja [Guardrails](guardrails.md). |
| `terms-acceptance` | A etapa de termos é pulada: novos usuários vão direto à etapa de persona (e o portão do BD nunca pede uma linha de aceite). Desligado por padrão. |

Chaves ausentes valem como habilitadas, **exceto `terms-acceptance`, que fica
desligada a menos que habilitada** — um framework neutro quanto ao domínio não
pode presumir que o app tem termos a aceitar. Desligue todo o subsistema com
`interaction-assessment: false` (isso também poupa uma chamada de LLM por turno).

### Aceite dos termos

Quando habilitado, a primeira mensagem do agente de boas-vindas pede ao usuário
que aceite os Termos de Uso, e `accept_terms_and_conditions` registra o aceite na
tabela `user_terms_acceptance`. O `file` é o texto de referência que o agente
pode citar se o usuário fizer perguntas (o texto completo nunca é colado sem ser
solicitado); `url` é opcional e, quando definida, é enviada literalmente nessa
primeira mensagem. Um `file` ausente ou ilegível falha na inicialização — o
consentimento nunca é registrado sem termos que o usuário pudesse ter lido. Os
caminhos são resolvidos relativos ao `semente.yaml`.

O primeiro `semente feature terms-acceptance --enable` (ou
`feature add terms-acceptance`) cria `domain/terms_example.md` e configura o
`file` para você; substitua esse exemplo pelos seus termos reais. Arquivos
existentes e um `file` já configurado nunca são sobrescritos.

### `terms_text` legado

A referência dos termos costumava ficar no `agents.yml`
(`welcoming_agent.terms_text`). Agora ela vem de
`features.terms-acceptance.file`; os apps podem apagar a chave antiga dos seus
prompts.

> **Aliases legados:** as antigas chaves `features.feedback_workflow` e
> `features.feedback` ainda carregam (mescladas em `interaction-assessment`, com
> avisos de depreciação) — renomeie-as no seu manifesto.
>
> **Alias legado:** a antiga chave `features.pii_guardrail` ainda carrega
> (normalizada para `guardrails`, com um aviso de depreciação) — renomeie-a no
> seu manifesto.

## Resolução de modelos

Os modelos são configurados principalmente por variáveis de ambiente:

| Variável de ambiente | Descrição |
|---|---|
| `PRIMARY_MODEL_PROVIDER` | `google` ou `ollama` |
| `PRIMARY_MODEL_ID` | ex.: `gemini-3.5-flash-lite` |
| `FALLBACK_MODEL_PROVIDER` / `FALLBACK_MODEL_ID` | Modelo de fallback opcional |
| `GOOGLE_API_KEY` | Obrigatória para o provedor `google` |
| `OLLAMA_API_KEY` / `OLLAMA_HOST` | Para o provedor `ollama` |

O bloco `models` do manifesto sobrescreve essas variáveis por app:

```yaml
models:
  primary: { provider: google, id: gemini-3.5-flash-lite }
  fallback: { provider: ollama, id: gemma4:31b-cloud }
```

## Variáveis de ambiente

O Semente lê a configuração de um arquivo `.env` no diretório de trabalho
(carregado via `python-dotenv`).

| Variável | Finalidade |
|---|---|
| `APP_ENV` | `development` (padrão), `stagging` ou `production` |
| `DATABASE_TYPE` | `sqlite` (dev) ou `postgres` (prod) |
| `SEMENTE_MANIFEST` | Caminho do manifesto (padrão `semente.yaml`) |
| `SEMENTE_ENGINE` | Engine quando o manifesto não tem campo `engine` (`agno`, `adk`, `bare`) |
| `SEMENTE_DEMO` | Definida por `semente launch streamlit --demo`; inicia o domínio de demonstração embutido |
| `SEMENTE_PROMPTS_DIR` | Diretório de prompts (sobrescrito pelo `prompts_dir` do manifesto) |
| `TTS_MODEL` | ID do modelo TTS (padrão `gemini-3.1-flash-tts-preview`) |
| `POSTGRES_*` | Conexão PostgreSQL (prod) |
| `PGVECTOR_*` | Conexão PgVector (base de conhecimento) |
| `WHATSAPP_*` | Credenciais da WhatsApp Business API |
| `VALKEY_*` | Valkey/Redis (debouncing do WhatsApp, prod) |
| `GEE_*` | Conta de serviço do Earth Engine (domínios geoespaciais) |
| `S3_*` | Armazenamento compatível com S3 (mídia, prod) |

Veja o `.env.example` no repositório para a lista completa.
