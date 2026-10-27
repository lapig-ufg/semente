# Primeiros Passos

Um app Semente é um **domínio** (suas ferramentas + conhecimento + prompts) mais
um **manifesto** (`semente.yaml`). O framework monta o pipeline multiagente (o
`Harness`) e os canais ao redor deles. O Semente é livre de engine por
construção — o domínio nunca importa o framework de agentes.

## Instalação

```bash
pip install semente-agents
```

Para domínios geoespaciais, adicione os extras necessários:

```bash
pip install "semente-agents[gee,weather,knowledge]"
```

| Extra | O que fornece |
|---|---|
| `gee` | Earth Engine, DuckDB, GeoPandas, xarray, shapely |
| `weather` | Ferramentas de previsão do Open-Meteo |
| `knowledge` | PgVector (KB vetorial para o agente de perguntas e respostas) |

## Primeira execução — o assistente de configuração

Na primeira vez que você roda `semente launch streamlit` (com ou sem `--demo`)
em uma pasta, um assistente interativo verifica o **ambiente efetivo** — suas
variáveis de shell mais o `.env` local — procurando os valores de que o modelo
precisa:

```
Semente needs a few values to run the model (saved to .env, asked only once):
Model provider (google/ollama) [google]:
Model ID [gemini-3.5-flash-lite]:
GOOGLE_API_KEY: ********
Saved to .env.
```

- Só os valores **ausentes** são perguntados — um `.env` com apenas uma lacuna
  preenche só essa lacuna.
- As respostas são salvas em `./.env`, então o assistente não roda de novo.
- Variáveis de shell exportadas contam como já definidas (sem insistência).
- Contextos não interativos (Docker, CI) nunca perguntam: um aviso lista o que
  falta e a execução prossegue.

## Experimente primeiro o agente de demonstração

Ainda não tem um app? Rode o agente padrão embutido — ele **não** precisa de
`semente.yaml`, nem de módulo `domain/`, nem de prompts: só dos valores do
assistente acima.

```bash
uv run semente launch streamlit --demo
```

Isso inicia um agente limpo, sem ferramentas, com os prompts padrão embutidos —
a forma mais rápida de verificar a configuração do modelo e ver o pipeline de
chat (onboarding, persona, feedback) funcionando de ponta a ponta.

Sem `--demo`, o comando exige um manifesto — `./semente.yaml` ou a variável de
ambiente `SEMENTE_MANIFEST` — e encerra com uma dica apontando para `--demo`
quando nenhum dos dois existe.

## Os dois arquivos que você escreve

Pule esta seção com `semente init` — ele cria os dois arquivos (além de
`.env.example`, `main.py` e arquivos de prompts) para você.

### 1. `domain/__init__.py` — seu domínio

```python
from semente import tool
from semente.domain import DomainSpec

@tool(description="Devolve a mensagem recebida ao usuário.")
def echo(message: str) -> str:
    return f"Echo: {message}"

domain_spec = DomainSpec(
    name="My App",
    tools=[echo],
)
```

### 2. `semente.yaml` — seu manifesto

```yaml
name: my-app
domain_module: domain
channels: [streamlit]
```

## Execute

```bash
export GOOGLE_API_KEY=your-gemini-key   # ou deixe o assistente da primeira execução perguntar
semente launch streamlit
```

Só isso. O framework liga o onboarding, a cadeia de guardrails, o ciclo de
feedback, a sumarização e a sua ferramenta `echo` em um chat funcional.
Adicione segurança de entrada ao seu domínio — veja [Guardrails](/pt/guide/guardrails).

## Estrutura do projeto

```
my-app/
├── domain/
│   ├── __init__.py      # expõe `domain_spec`
│   └── prompts/         # agents.yml, tools.yml, hooks.yml
├── semente.yaml         # manifesto
├── .env                 # segredos (chaves de API, BD, WhatsApp)
└── main.py              # entrada FastAPI opcional (WhatsApp)
```

## Próximos passos

- [Referência da CLI](/pt/guide/cli) — `init`, `config`, `status`, `launch`
- [O Domínio](/pt/guide/domain) — tudo o que o `DomainSpec` pode conter
- [Referência do Manifesto](/pt/guide/manifest) — todas as opções do `semente.yaml`
- [Implantar o App de Exemplo](/pt/deployment/toy-app) — um exemplo completo e executável
