# Groot — o assistente da documentação do Semente

O **Groot** é um app Semente mínimo (`examples/groot/`) que lê **esta própria
documentação** e ajuda você em todos os aspectos dela usando o Gemini: explica
conceitos, indica a página certa, guia passo a passo, gera exemplos de
configuração e código, ajuda a resolver problemas e a comparar opções, em
português ou inglês. É o menor
exemplo útil de um *domínio*: três ferramentas Python simples, sem banco
vetorial e sem embeddings.

```
Usuário ──► chat Streamlit ──► Harness ──► agente Agno (Gemini)
                                             ├── list_docs()
                                             ├── search_docs(query)
                                             └── read_doc(path)  ──► docs/**/*.md
```

O Semente fornece o pipeline (onboarding, guardrails, sumarização, a engine Agno,
a interface de chat). O exemplo só entrega o **domínio**: como ler a
documentação.

## Pré-requisitos

- **Python 3.12+** e **uv** (ou pip)
- Uma **chave de API do Google Gemini**
- Um clone do repositório (o agente lê a pasta `docs/`)

## 1. Instale e execute

```bash
git clone https://github.com/lapig-ufg/semente.git
cd semente
uv venv .venv && source .venv/bin/activate
uv pip install -e .

cd examples/groot
cp .env.example .env          # defina GOOGLE_API_KEY (ou deixe o assistente da primeira execução perguntar)
semente launch streamlit
```

Abra `http://localhost:8501` e pergunte algo:

> Como habilito o aceite dos termos?
> Qual a diferença entre as engines `agno` e `bare`?

O agente busca na documentação, lê a página relevante e responde citando o
arquivo usado (por exemplo `pt/guide/manifest.md`). Ele responde no seu idioma e
lê as páginas em inglês ou português conforme o caso.

## 2. Os arquivos

```
examples/groot/
├── semente.yaml              # manifesto: engine agno, streamlit, modelo Gemini
├── .env.example
├── main.py                   # entrada FastAPI opcional (WhatsApp)
└── domain/
    ├── __init__.py           # as três ferramentas + domain_spec
    └── prompts/
        ├── agents.yml        # as instruções do agente
        ├── tools.yml
        └── hooks.yml
```

### O manifesto

```yaml
name: groot
language: en
domain_module: domain
prompts_dir: domain/prompts
engine: agno
channels:
- streamlit
features:
  onboarding: false          # responde direto, sem etapa de boas-vindas
  tts: false
  summarization: true
  guardrails: true
  interaction-assessment: false   # evita uma chamada extra ao LLM por turno
models:
  primary:
    provider: google
    id: gemini-3.5-flash-lite
```

### O domínio — três ferramentas

Cada ferramenta é uma função Python simples decorada com `@tool` (veja a
[API do Domínio](/pt/guide/domain-api)). O Semente as adapta para a engine Agno.

```python
from semente import tool
from semente.domain import DomainSpec

@tool(description="Lists every page of the Semente documentation (path + title). ...")
def list_docs(language: str = "en") -> str: ...

@tool(description="Keyword search over the Semente documentation. ...")
def search_docs(query: str, language: str = "en", max_results: int = 5) -> str: ...

@tool(description="Reads one documentation page in full. ...")
def read_doc(path: str) -> str: ...

domain_spec = DomainSpec(
    name="groot",
    tools=[list_docs, search_docs, read_doc],
)
```

| Ferramenta | O que faz |
|---|---|
| `list_docs(language)` | Lista as páginas (`en` = `docs/`, `pt` = `docs/pt/`) com seus títulos |
| `search_docs(query, language, max_results)` | Pontua cada seção (dividida nos títulos `#`/`##`/`###`) por ocorrências das palavras-chave, com peso maior para o título, e devolve as melhores com o caminho |
| `read_doc(path)` | Devolve uma página. O caminho é resolvido apenas dentro da pasta de docs — `..` e arquivos que não sejam `.md` são recusados |

O código completo está em
[`domain/__init__.py`](https://github.com/lapig-ufg/semente/blob/main/examples/groot/domain/__init__.py).

### As instruções

O `domain/prompts/agents.yml` manda o agente buscar primeiro, ler a página
quando o resultado estiver incompleto, citar o caminho, nunca inventar comandos e
admitir quando a documentação não cobre a pergunta:

```yaml
single_agent:
  name: "Groot"
  instructions_default: |
    You are Groot. Your mission is to help users UNDERSTAND the Semente framework ... Everything you know comes from the official documentation, reached through your tools.
    ONLY the official documentation, which you reach through your tools.
    1. Call `search_docs` with a few keywords from the question. ...
    2. When a search hit looks relevant but incomplete, call `read_doc` ...
    3. Answer from what you read. Cite the page path(s) you used.
    4. If the docs do not cover the question, say so plainly.
```

Tudo que não é definido aqui (onboarding, persona…) recorre aos padrões neutros do
Semente — veja [Prompts e i18n](/pt/guide/prompts).

## Sem onboarding

Por padrão o Semente executa um onboarding curto (**nome** e **função** do
usuário) antes de o agente principal responder. Um bot de documentação deve
simplesmente responder, então o Groot desliga isso no `semente.yaml`:

```yaml
features:
  onboarding: false
```

Todo turno vai direto ao Groot e às suas ferramentas de documentação, sem etapa
de boas-vindas e sem persona a preencher. Veja a
[Referência do Manifesto](/pt/guide/manifest#interruptores-de-features).
## 3. Use outra pasta de documentação

Por padrão as ferramentas leem `../../docs` em relação ao exemplo. Aponte para
qualquer lugar com uma variável de ambiente:

```ini
# .env
SEMENTE_DOCS_DIR=/caminho/para/outra/docs
```

O mesmo exemplo vira um bot de perguntas e respostas para qualquer pasta de
Markdown: troque a pasta e o prompt do `agents.yml`.

## 4. Sirva no WhatsApp

Habilite o canal e siga os passos de produção do
[guia do App de Exemplo](/pt/deployment/toy-app#_6-implante-em-producao-whatsapp):

```bash
semente channel whatsapp --enable
python main.py
```

## Para ir além

- **Recuperação melhor:** troque `search_docs` por uma base de conhecimento
  vetorial (`DomainSpec.knowledge`) — veja [O Domínio](/pt/guide/domain).
- **Outras engines:** defina `engine: adk` ou `bare` — veja [Engines](/pt/guide/engines).
- **Segurança:** adicione [guardrails](/pt/guide/guardrails) se usuários puderem colar segredos.
- **Fonte amigável para IA:** o site também publica
  [`/llms.txt`](https://lapig-ufg.github.io/semente/llms.txt) e
  `/llms-full.txt`, úteis se você preferir entregar a documentação direto a um
  modelo.
