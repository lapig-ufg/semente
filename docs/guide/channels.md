# Channels

Semente ships four interfaces: **REST** (plain HTTP API, always on),
**WhatsApp** (production, for end users), **A2A** (agent-to-agent) and
**Streamlit** (development, for debugging). All of them run the same Harness.
`SementeApp` mounts REST unconditionally and the others according to the
manifest `channels` list. Interfaces live in `semente/api/interfaces/`.

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
from semente.api import SementeApp

app = SementeApp("semente.yaml").build_app()

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

## REST

The REST interface exposes the agent as a plain HTTP API, for web frontends,
mobile apps and integrations that do not speak WhatsApp or A2A. It runs the
same Harness, so guardrails, summarization, sessions and media all apply.

It is the **default interface**: `SementeApp` always mounts it — there is no
`channels` entry and nothing to enable. Just start the app:

```bash
export REST_API_KEY=change-me
python main.py            # REST on :3000
```

| Endpoint | Auth | Purpose |
|---|---|---|
| `POST /runs` | Bearer | One conversation turn |
| `GET /sessions/{session_id}/session` | Bearer | Read the persisted session |
| `POST /sessions/{session_id}/session` | Bearer | Upsert the session (partial merge) |
| `GET /health` | public | Liveness probe |

Interactive OpenAPI docs are served at `/docs` (schema at `/openapi.json`), so
you can try the routes straight from the browser.

Authentication **is mandatory and Bearer-only**: every route except `/health`
requires `Authorization: Bearer <REST_API_KEY>`. If `REST_API_KEY` is not
configured, the protected routes answer `503` — the API never runs open.

### Running a turn

`POST /runs` takes either JSON (files inline as base64) or
`multipart/form-data` (real uploads).

```bash
curl -s http://localhost:3000/runs \
  -H "Authorization: Bearer $REST_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"message": "What is the Harness?", "user_id": "u1", "session_id": "s1"}'
```

```json
{"run_id": "run_…", "session_id": "s1", "user_id": "u1", "content": "…",
 "images": [], "audio": [], "videos": [], "files": []}
```

`session_id` is generated (`rest:<user_id>:<random>`) and echoed back when
omitted; `user_id` defaults to `rest:anonymous`. Generated media comes back
base64-encoded (`base64`), or as `url` when the engine produced a link.

### Files

JSON bodies carry files in `files`, as base64 `data` (a plain payload or a
`data:` URL) or a `url` the engine fetches:

```bash
curl -s http://localhost:3000/runs \
  -H "Authorization: Bearer $REST_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"message": "read this", "files": [
        {"name": "photo.png", "mime_type": "image/png", "data": "iVBORw0…"}
      ]}'
```

With multipart, name the file parts `files` (type inferred) or declare it in
the field name — `images`, `audio`, `videos`, `documents`:

```bash
curl -s http://localhost:3000/runs \
  -H "Authorization: Bearer $REST_API_KEY" \
  -F 'message=describe this' \
  -F 'images=@photo.png' \
  -F 'documents=@report.pdf'
```

`files_metadata` (a JSON string in multipart, a list or filename-keyed object
in JSON) overrides the classification per file:

```json
[{"name": "report.pdf", "type": "document", "mime_type": "application/pdf"}]
```

Limits: `REST_MAX_FILES` (default 10) and `REST_MAX_FILE_BYTES` (default
25 MB) — exceeding either returns `413`.

### Sessions

`GET /sessions/{session_id}/session` returns `user_id`, `session_state`, the
conversation `runs` and the latest `interaction_assessment`; add `?user_id=`
to scope the lookup. `404` when absent, `503` when the app has no session
storage.

`POST /sessions/{session_id}/session` is an upsert with partial merge:
`session_state` is deep-merged, `runs` and `interaction_assessment` replace
the stored values when present, and `user_id` is required only to create a
new row. Writes go through the same guardrail sanitization the pipeline uses
before persisting.

```bash
curl -s -X POST http://localhost:3000/sessions/s1/session \
  -H "Authorization: Bearer $REST_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"user_id": "u1", "session_state": {"user_persona": {"name": "Ana"}}}'
```

| Variable | Purpose |
|---|---|
| `REST_API_KEY` | **Required.** Bearer key for every route except `/health` |
| `REST_MAX_FILES` | Files per request (default 10) |
| `REST_MAX_FILE_BYTES` | Per-file upload cap (default 25 MB) |

## Adding an interface

An interface is a FastAPI router factory living in
`semente/api/interfaces/`. Two ways to add one:

```python
from semente.api import SementeApp
from semente.api.interfaces import HTTP_INTERFACES

# 1. register the factory: mounted when `channels` includes the name
HTTP_INTERFACES["metrics"] = lambda harness, manifest: Metrics(harness=harness)

# 2. or mount an ad-hoc interface on one app
semente_app = SementeApp("semente.yaml")
semente_app.build_app()          # FastAPI instance + default interfaces
semente_app.register("metrics", Metrics(harness=semente_app.harness))
```

Both need a ``get_router()`` returning an ``APIRouter`` (or declare ``name``
and ``get_router`` and let ``register`` handle it). REST is always mounted;
the rest follow the manifest `channels` list. Interfaces that do not serve
HTTP (Streamlit, MCP) run in their own process and are listed in
`semente/api/interfaces/__init__.py` under `CLI_INTERFACES`.
