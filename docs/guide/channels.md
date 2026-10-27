# Channels

Semente ships three channels: **WhatsApp** (production, for end users),
**Streamlit** (development, for debugging) and **A2A** (agent-to-agent). All of
them run the same Harness.

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

## A2A

The A2A channel exposes the agent over the
[Agent2Agent protocol](https://a2a-protocol.org), so other agents (any
framework) can discover and call it. It goes through the same Harness as the
other channels, so guardrails, summarization and sessions all apply.

Enable it and run the FastAPI entry point:

```bash
semente channel a2a --enable
python main.py
```

| Endpoint | Purpose |
|---|---|
| `GET /.well-known/agent-card.json` | Agent Card (discovery). `/.well-known/agent.json` also works |
| `POST /a2a` | JSON-RPC 2.0 endpoint |

```bash
curl -s http://localhost:3000/a2a -H 'Content-Type: application/json' -d '{
  "jsonrpc": "2.0", "id": 1, "method": "message/send",
  "params": {"message": {
    "kind": "message", "role": "user", "messageId": "m1",
    "parts": [{"kind": "text", "text": "What is the Harness?"}]
  }}
}'
```

The reply is a `message` with a text part and a `contextId`. Send the same
`contextId` back to continue the conversation (it maps to the Semente
session).

**Scope.** Text only. `message/stream` returns `-32004` (unsupported);
`tasks/get`, `tasks/cancel` and `tasks/resubscribe` return `-32001`
(no tasks — replies are immediate messages). Unknown methods return `-32601`;
malformed input returns `-32700`/`-32600`/`-32602`; a Harness failure
returns `-32603` without leaking details.

The Agent Card is built from the manifest `name` and the optional
[`a2a` block](/guide/manifest#a2a-agent-card).

| Variable | Purpose |
|---|---|
| `A2A_API_KEY` | If set, `POST /a2a` requires `Authorization: Bearer <key>` or `X-API-Key`. The card stays public and advertises the scheme |
| `A2A_PUBLIC_URL` | Public base URL written in the card (set it behind a proxy/ngrok) |

### Use it as an MCP tool

`semente mcp` wraps **any** A2A agent as a single
[MCP](https://modelcontextprotocol.io) tool, so MCP clients (Claude Desktop,
Cursor, ...) can ask it questions. It is a stdio server that forwards each call
to the agent's `POST /a2a`; the tool is named after the Agent Card
(`ask_<name>`) and keeps one conversation per server process.

```bash
pip install 'semente-agents[mcp]'
semente mcp --url http://localhost:3000
```

```json
{
  "mcpServers": {
    "groot": {
      "command": "semente",
      "args": ["mcp", "--url", "http://localhost:3000"]
    }
  }
}
```

| Option | Purpose |
|---|---|
| `--url` | Base URL of the A2A agent (required) |
| `--name` | Tool/agent name (default: the Agent Card name) |
| `--api-key` | Bearer key (default: `A2A_API_KEY`) |

The tool takes `message` and an optional `context_id` to pick another
conversation.

## Adding a channel

Channels are FastAPI router factories wired in `semente.build.build_app`.
To add one, implement the router and register it in `build_app` based on the
manifest `channels` list.
