# Referência da CLI

O comando `semente` gerencia todo o ciclo de vida do app — criar, configurar,
inspecionar e executar. Todos os comandos funcionam a partir do diretório do app
(onde está o `semente.yaml`).

Comportamento da ajuda: executar um grupo de comandos sem o argumento
(`semente feature`, `semente channel`, `semente provider`) imprime a ajuda
daquele grupo; qualquer argumento inválido imprime a ajuda do comando onde o
erro aconteceu — equivalente a digitar `-h` ali.

```bash
semente init          # cria a estrutura de um novo app
semente feature       # gerencia features (ls, actives, add, --enable/--disable)
semente channel       # gerencia canais (ls, actives, --enable/--disable)
semente provider      # modelos primário/fallback e chaves de API
semente status        # visão geral do app + verificações (doctor)
semente launch        # executa uma interface
```

## `semente init [directory]`

Cria um app mínimo funcional com os padrões embutidos e neutros quanto ao
domínio do framework:

```
my-app/
├── semente.yaml            # manifesto: features, canal streamlit, bloco de modelo
├── .env.example            # todos os grupos de variáveis, comentados
├── domain/
│   ├── __init__.py        # domain_spec com uma ferramenta echo de exemplo
│   └── prompts/           # agents.yml, tools.yml, hooks.yml (padrões embutidos)
├── main.py                 # entrada FastAPI (webhook do WhatsApp)
└── .gitignore
```

Opções:

| Flag | Descrição |
|---|---|
| `--name` | Nome do app (padrão: nome do diretório) |
| `--language` | Idioma do agente (padrão: `en`) |
| `--provider` | `google` (padrão) ou `ollama` |
| `--force` | Sobrescreve arquivos existentes |
| `--non-interactive` | Nunca pergunta (usa os padrões) |

Arquivos existentes nunca são sobrescritos sem `--force`. Se o `semente.yaml` já
existe, o init se recusa e aponta para `semente feature` / `semente channel` /
`semente provider`.

## `semente feature`

Gerencia o bloco `features` do manifesto. Resolução: variável de ambiente
`SEMENTE_MANIFEST`, depois `./semente.yaml`. Sem manifesto, encerra com uma dica
acionável. A alternância usa flags: uma entre `--enable`/`--disable` é
obrigatória, e elas são mutuamente exclusivas. Digitar `semente feature <name>`
sem flag imprime o status daquela feature mais os comandos exatos para
habilitá-la ou desabilitá-la.

```bash
semente feature ls                              # todas as features + status (enabled/disabled/default)
semente feature actives                          # apenas as features ativas
semente feature add guardrails                  # cria um exemplo + habilita
semente feature add tts                         # interna do framework: apenas habilita
semente feature terms-acceptance --enable       # primeira habilitação: cria + configura o exemplo de termos
semente feature tts --enable
semente feature tts --disable                   # só no manifesto — o código não é tocado
```

Features suportadas:

| Feature | Significado |
|---|---|
| `tts` | Ferramenta TTS no agente de boas-vindas (respostas em áudio) |
| `summarization` | Resumo contínuo da conversa (a cada 6 turnos) |
| `interaction-assessment` | Ciclo de satisfação/persona, ciclos de remediação, captura DPO/SFT (`{enable, window_size}`) |
| `guardrails` | Guardrails de entrada plugáveis declarados no `DomainSpec` |
| `terms-acceptance` | Portão de termos no onboarding: consentimento na primeira mensagem + registro no BD (`{enable, file, url}`); **desligado por padrão** |

O `add` escreve um exemplo no lado do app quando existe um e habilita a feature:
`guardrails` cria `domain/guardrails_example.py`; `terms-acceptance` cria
`domain/terms_example.md` e aponta `features.terms-acceptance.file` para ele.
Habilitar `terms-acceptance` pela **primeira vez** (`add` ou `--enable`) faz o
mesmo, para que o portão nunca comece sem termos a mostrar ao usuário. Arquivos
existentes e um `file` já configurado nunca são sobrescritos. Para features
internas do framework, o `add` se comporta como `enable`: o framework é dono do
comportamento; não há código de app a criar.

> O `--disable` nunca apaga o seu código. Ele só altera a chave do manifesto;
> execute `semente feature <name> --enable` novamente para religá-la.

## `semente channel`

Mesmo estilo de flags do `feature`, operando na lista `channels` do manifesto.

```bash
semente channel ls                    # todos os canais + status
semente channel actives               # apenas canais habilitados
semente channel whatsapp --enable     # channels: + whatsapp
semente channel whatsapp --disable    # channels: - whatsapp
semente channel whatsapp              # status + as dicas de habilitar/desabilitar
```

| Canal | Significado |
|---|---|
| `streamlit` | Chat web local (interface amigável ao desenvolvimento, com painel de depuração) |
| `whatsapp` | Canal de webhook do WhatsApp (montado pelo `build_app`; execute via `main.py`) |

## `semente provider`

Gerencia a configuração de modelos: provedores, ids de modelo, o fallback
opcional e as chaves de API. O bloco de modelo do `.env` é a base; um bloco
`models:` do manifesto o sobrescreve — `primary`/`fallback` escrevem esse bloco,
e as chaves (segredos) são gravadas no `.env`, nunca no `semente.yaml`.

```bash
semente provider ls                              # configuração efetiva + chaves ausentes
semente provider primary google --model gemini-2.0-flash
semente provider primary ollama                  # id intocado (o .env / assistente cuida)
semente provider fallback ollama --model gemma4:31b-cloud
semente provider fallback --disable              # remove o fallback do manifesto
semente provider key google                      # entrada oculta -> GOOGLE_API_KEY no .env
semente provider key ollama                      # OLLAMA_HOST + OLLAMA_API_KEY
```

Provedores: `google` (Gemini) e `ollama` (local). Uma flag `--model` é aceita por
chamada de `primary`/`fallback`. O `ls` marca as chaves dos provedores como
`set`/`missing` em relação ao ambiente efetivo (shell + `.env`).

## `semente status`

Imprime o app de relance (tabelas rich):

- **App** — nome, idioma, engine, módulo de domínio, diretório de prompts, caminho do manifesto
- **Channels** — canais habilitados
- **Features** — ligadas/desligadas (chaves ausentes valem como habilitadas)
- **Models** — provedor e id primário/fallback
- **Environment** — variáveis de modelo necessárias, presentes/ausentes, chaves de API mascaradas
- **Doctor** — verificações estáticas: o módulo de domínio expõe `domain_spec`
  (analisado por AST, nunca importado), e o diretório de prompts tem os três
  arquivos YAML

Sem manifesto, imprime uma dica amigável do `semente init` (saída 0 — é
informativo, não um erro).

## `semente launch <interface>`

Inicia uma interface do app.

```bash
semente launch streamlit          # seu app (lê SEMENTE_MANIFEST ou ./semente.yaml)
semente launch streamlit --demo  # o agente padrão embutido — sem arquivos de app
```

A primeira execução em uma pasta dispara o **assistente de configuração**:
valores de modelo ausentes (provedor, ID do modelo, chave de API) são
perguntados interativamente, salvos em `./.env` e nunca mais perguntados. Só as
lacunas são perguntadas; variáveis de shell exportadas contam como definidas.
Contextos não interativos (Docker, CI) recebem um aviso listando o que falta em
vez de perguntas.

`semente launch whatsapp` explica que o WhatsApp é um canal de webhook — ele
roda via `python main.py` (FastAPI), não por um launcher. Interfaces futuras
(Instagram, ...) aparecerão aqui.
