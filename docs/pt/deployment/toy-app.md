# Implantar o App de Exemplo

O **App de Exemplo** (Toy App) é a aplicação Semente mínima — o *domínio Echo*
em `examples/minimal-chat/`. Ele tem uma ferramenta (`echo`), nenhuma base de
conhecimento e nenhuma skill. Serve para provar que o framework inicia e como
ponto de partida para o seu próprio app.

Este guia mostra como executá-lo localmente e implantá-lo em produção.

## Pré-requisitos

- **Python 3.12+**
- **uv** (recomendado) ou pip
- Uma **chave de API do Google Gemini** (ou [Ollama](https://ollama.com) para modelos locais)

## 1. Obtenha o código

```bash
git clone https://github.com/lapig-ufg/semente.git
cd semente
```

## 2. Crie um ambiente virtual e instale

```bash
uv venv .venv
source .venv/bin/activate
uv pip install -e .
```

Isso instala o pacote `semente` e a CLI `semente`.

## 3. Configure o ambiente

```bash
cd examples/minimal-chat
cp .env.example .env
```

Edite o `.env` e defina sua chave do Gemini:

```ini
APP_ENV=development
GOOGLE_API_KEY=your-gemini-api-key
```

> **Usando Ollama?** Defina `PRIMARY_MODEL_PROVIDER=ollama`,
> `PRIMARY_MODEL_ID=<modelo>` e `OLLAMA_HOST=http://localhost:11434`.

## 4. Execute a interface Streamlit

```bash
export SEMENTE_MANIFEST=semente.yaml
semente launch streamlit
```

Abra `http://localhost:8501`. Você deve ver a interface de chat. Digite uma
mensagem e o assistente Echo responde com `Echo: <sua mensagem>`.

## 5. O que acabou de acontecer

1. `semente launch streamlit` iniciou o webapp Streamlit que acompanha o Semente.
2. O webapp leu `SEMENTE_MANIFEST` → `semente.yaml`.
3. O Semente importou o pacote `domain` (seu `domain_spec`), construiu o agente
   único com a ferramenta `echo` e montou o pipeline do Harness:
   `Entrada → Cadeia de guardrails → Onboarding → Agente Echo → Saída`.
4. A interface de chat conversa com esse agente.

## 6. Implante em produção (WhatsApp)

O canal de produção é o WhatsApp. Você precisa de um app da
[WhatsApp Business API](https://developers.facebook.com/docs/whatsapp/cloud-api)
e de uma instância Valkey/Redis para o debouncing de mensagens.

### 6.1 Crie o ponto de entrada FastAPI

```python
# main.py
from semente.build import build_app

app = build_app("semente.yaml")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=3000, reload=True)
```

### 6.2 Configure o WhatsApp e o Valkey

```ini
# .env
APP_ENV=production
DATABASE_TYPE=postgres
POSTGRES_HOST=...
POSTGRES_PORT=5432
POSTGRES_DBNAME=...
POSTGRES_USER=...
POSTGRES_PASSWORD=...

WHATSAPP_ACCESS_TOKEN=...
WHATSAPP_VERIFY_TOKEN=...
WHATSAPP_PHONE_NUMBER_ID=...
WHATSAPP_APP_SECRET=...

VALKEY_HOST=valkey
VALKEY_PORT=6379
VALKEY_DB=0
```

### 6.3 Execute com Docker Compose

```yaml
# compose.yaml
services:
  app:
    build: .
    command: python main.py
    ports: ["3000:3000"]
    env_file: .env
    depends_on: [valkey]
  valkey:
    image: valkey/valkey:8
```

```bash
docker compose up --build
```

### 6.4 Exponha o webhook com ngrok

```bash
ngrok config add-authtoken <AUTH>
ngrok http 3000
```

Defina a URL do webhook do WhatsApp com a URL HTTPS do ngrok e verifique com
`WHATSAPP_VERIFY_TOKEN`.

## Próximos passos

- Troque a ferramenta `echo` pelas suas — veja [O Domínio](/pt/guide/domain).
- Adicione uma base de conhecimento para perguntas e respostas — veja [O Domínio](/pt/guide/domain#domainspec).
- Configure o app com a CLI — veja [Referência da CLI](/pt/guide/cli).
- Veja um domínio real no [Pasto Legal](/pt/showcase/pasto-legal).
