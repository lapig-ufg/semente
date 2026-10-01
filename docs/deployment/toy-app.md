# Deploy the Toy App

The **Toy App** is the minimal Semente application — the *Echo domain* in
`examples/echo_domain/`. It has one tool (`echo`), no knowledge base, and no
skills. It exists to prove the framework boots and to serve as the starting
point for your own app.

This guide walks through running it locally and deploying it to production.

## Prerequisites

- **Python 3.12+**
- **uv** (recommended) or pip
- A **Google Gemini API key** (or [Ollama](https://ollama.com) for local models)

## 1. Get the code

```bash
git clone https://github.com/leandroleal/semente.git
cd semente
```

## 2. Create a virtual environment and install

```bash
uv venv .venv
source .venv/bin/activate
uv pip install -e .
```

This installs the `semente` package and the `semente` CLI.

## 3. Configure the environment

```bash
cd examples/echo_domain
cp .env.example .env
```

Edit `.env` and set your Gemini key:

```ini
APP_ENV=development
GOOGLE_API_KEY=your-gemini-api-key
```

> **Using Ollama instead?** Set `PRIMARY_MODEL_PROVIDER=ollama`,
> `PRIMARY_MODEL_ID=<model>`, and `OLLAMA_HOST=http://localhost:11434`.

## 4. Run the Streamlit interface

```bash
export SEMENTE_MANIFEST=semente.yaml
semente launch streamlit
```

Open `http://localhost:8501`. You should see the chat UI. Type a message and
the Echo assistant replies with `Echo: <your message>`.

## 5. What just happened

1. `semente launch streamlit` launched the Streamlit webapp bundled with Semente.
2. The webapp read `SEMENTE_MANIFEST` → `semente.yaml`.
3. Semente imported the `domain` package (your `domain_spec`), built the single
   agent with the `echo` tool, and assembled the Semente pipeline:
   `Input → PII guardrail → Onboarding → Echo agent → Output`.
4. The chat UI talks to that agent.

## 6. Deploy to production (WhatsApp)

The production channel is WhatsApp. You need a
[WhatsApp Business API](https://developers.facebook.com/docs/whatsapp/cloud-api)
app and a Valkey/Redis instance for message debouncing.

### 6.1 Create the FastAPI entry point

```python
# main.py
from semente.build import build_app

app = build_app("semente.yaml")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=3000, reload=True)
```

### 6.2 Configure WhatsApp and Valkey

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

### 6.3 Run with Docker Compose

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

### 6.4 Expose the webhook with ngrok

```bash
ngrok config add-authtoken <AUTH>
ngrok http 3000
```

Set the WhatsApp webhook URL to the ngrok HTTPS URL and verify with
`WHATSAPP_VERIFY_TOKEN`.

## Next steps

- Replace the `echo` tool with your own tools — see [The Domain](/guide/domain).
- Add a knowledge base for Q&A — see [Prompts & i18n](/guide/prompts).
- See a real domain in [Pasto Legal](/showcase/pasto-legal).
