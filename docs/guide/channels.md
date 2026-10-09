# Channels

Semente ships two channels: **WhatsApp** (production, for end users) and
**Streamlit** (development, for debugging). Both run the same Semente agent.

## Streamlit

The Streamlit UI is a chat interface with a debug panel (session state, agent
routing, tool calls, metrics).

```bash
export SEMENTE_MANIFEST=semente.yaml
semente launch streamlit
```

Or run the script directly:

```bash
streamlit run "$(python -c 'import semente, pathlib; print(pathlib.Path(semente.__file__).parent / "interfaces/streamlit/streamlit_webapp.py")')"
```

## WhatsApp

The WhatsApp channel is a FastAPI webhook for the
[WhatsApp Business API](https://developers.facebook.com/docs/whatsapp/cloud-api).
It handles:

- Webhook signature verification
- Media download (images, audio, video)
- Message **debouncing** (Valkey/Redis) — coalesces rapid messages
- Long-response **chunking** — splits `[PAUSA]`-tagged replies into paced blocks
- Typing indicators

### Entry point

```python
# main.py
from semente.build import build_app

app = build_app("semente.yaml")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=3000, reload=True)
```

```bash
python main.py
```

### Required environment

| Variable | Description |
|---|---|
| `WHATSAPP_ACCESS_TOKEN` | Cloud API access token |
| `WHATSAPP_VERIFY_TOKEN` | Webhook verification token |
| `WHATSAPP_PHONE_NUMBER_ID` | Phone number id |
| `WHATSAPP_APP_SECRET` | App secret (signature validation) |
| `VALKEY_HOST` / `VALKEY_PORT` / `VALKEY_DB` | Valkey/Redis for debouncing (prod) |

### Exposing locally with ngrok

```bash
ngrok config add-authtoken <AUTH>
ngrok http 3000
```

Point the WhatsApp webhook URL at the ngrok HTTPS URL.

## Adding a channel

Channels are FastAPI router factories wired in `semente.build.build_app`.
To add one, implement the router and register it in `build_app` based on the
manifest `channels` list.
