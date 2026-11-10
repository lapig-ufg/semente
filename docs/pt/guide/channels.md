# Canais

O Semente traz quatro interfaces: **REST** (API HTTP simples, sempre ativa),
**WhatsApp** (produção, para usuários finais), **A2A** (agente-para-agente) e
**Streamlit** (desenvolvimento, para depuração). Todas executam o mesmo
Harness. O `SementeApp` monta a REST incondicionalmente e as demais conforme a
lista `channels` do manifesto. As interfaces ficam em `semente/api/interfaces/`.

## Streamlit

A interface Streamlit é um chat com um painel de depuração (estado da sessão,
roteamento de agentes, chamadas de ferramentas, métricas).

```bash
export SEMENTE_MANIFEST=semente.yaml
semente launch streamlit
```

Ou execute o script diretamente:

```bash
streamlit run "$(python -c 'import semente, pathlib; print(pathlib.Path(semente.__file__).parent / "interfaces/streamlit/streamlit_webapp.py")')"
```

## WhatsApp

O canal WhatsApp é um webhook FastAPI para a
[WhatsApp Business API](https://developers.facebook.com/docs/whatsapp/cloud-api).
Ele cuida de:

- Verificação de assinatura do webhook
- Download de mídia (imagens, áudio, vídeo)
- **Debouncing** de mensagens (Valkey/Redis) — agrupa mensagens enviadas em rajada
- **Fracionamento** de respostas longas — divide respostas marcadas com `[PAUSA]` em blocos espaçados
- Indicadores de digitação

### Ponto de entrada

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

### Ambiente necessário

| Variável | Descrição |
|---|---|
| `WHATSAPP_ACCESS_TOKEN` | Token de acesso da Cloud API |
| `WHATSAPP_VERIFY_TOKEN` | Token de verificação do webhook |
| `WHATSAPP_PHONE_NUMBER_ID` | ID do número de telefone |
| `WHATSAPP_APP_SECRET` | Segredo do app (validação de assinatura) |
| `VALKEY_HOST` / `VALKEY_PORT` / `VALKEY_DB` | Valkey/Redis para debouncing (produção) |

### Expondo localmente com ngrok

```bash
ngrok config add-authtoken <AUTH>
ngrok http 3000
```

Aponte a URL do webhook do WhatsApp para a URL HTTPS do ngrok.

## A2A

O canal A2A expõe o agente pelo
[protocolo Agent2Agent](https://a2a-protocol.org), para que outros agentes
(de qualquer framework) o descubram e o chamem. Ele passa pelo mesmo Harness dos
demais canais, então guardrails, sumarização e sessões se aplicam.

Habilite-o e execute o ponto de entrada FastAPI:

```bash
semente channel a2a --enable
python main.py
```

| Endpoint | Finalidade |
|---|---|
| `GET /.well-known/agent-card.json` | Agent Card (descoberta). `/.well-known/agent.json` também funciona |
| `POST /a2a` | Endpoint JSON-RPC 2.0 |

```bash
curl -s http://localhost:3000/a2a -H 'Content-Type: application/json' -d '{
  "jsonrpc": "2.0", "id": 1, "method": "message/send",
  "params": {"message": {
    "kind": "message", "role": "user", "messageId": "m1",
    "parts": [{"kind": "text", "text": "What is the Harness?"}]
  }}
}'
```

A resposta é uma `message` com uma parte de texto e um `contextId`. Envie o
mesmo `contextId` de volta para continuar a conversa (ele corresponde à sessão
do Semente).

**Escopo.** Somente texto. `message/stream` retorna `-32004` (não
suportado); `tasks/get`, `tasks/cancel` e `tasks/resubscribe` retornam
`-32001` (sem tasks — as respostas são mensagens imediatas). Métodos
desconhecidos retornam `-32601`; entrada malformada retorna
`-32700`/`-32600`/`-32602`; uma falha do Harness retorna `-32603` sem
vazar detalhes.

O Agent Card é construído a partir do `name` do manifesto e do
[bloco `a2a`](/pt/guide/manifest#a2a-agent-card) opcional.

| Variável | Finalidade |
|---|---|
| `A2A_API_KEY` | Se definida, `POST /a2a` exige `Authorization: Bearer <chave>` ou `X-API-Key`. O card continua público e anuncia o esquema |
| `A2A_PUBLIC_URL` | URL pública base escrita no card (defina atrás de proxy/ngrok) |

### Use como ferramenta MCP

`semente mcp` encapsula **qualquer** agente A2A como uma única ferramenta
[MCP](https://modelcontextprotocol.io), para que clientes MCP (Claude Desktop,
Cursor, ...) possam fazer perguntas a ele. É um servidor stdio que repassa cada
chamada ao `POST /a2a` do agente; a ferramenta leva o nome do Agent Card
(`ask_<nome>`) e mantém uma conversa por processo do servidor.

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

| Opção | Finalidade |
|---|---|
| `--url` | URL base do agente A2A (obrigatória) |
| `--name` | Nome da ferramenta/agente (padrão: o nome do Agent Card) |
| `--api-key` | Chave Bearer (padrão: `A2A_API_KEY`) |

A ferramenta recebe `message` e um `context_id` opcional para escolher outra
conversa.

## REST

A REST expõe o agente como uma API HTTP simples, para frontends web, apps
móveis e integrações que não falam WhatsApp nem A2A. Ela roda o mesmo Harness,
então guardrails, sumarização, sessões e mídia continuam valendo.

É a **interface padrão**: o `SementeApp` sempre a monta — não há entrada em
`channels` nem nada para habilitar. Basta subir o app:

```bash
export REST_API_KEY=change-me
python main.py            # REST em :3000
```

| Rota | Auth | Finalidade |
|---|---|---|
| `POST /runs` | Bearer | Um turno de conversa |
| `GET /sessions/{session_id}/session` | Bearer | Ler a sessão persistida |
| `POST /sessions/{session_id}/session` | Bearer | Upsert da sessão (merge parcial) |
| `GET /health` | pública | Sonda de liveness |

A documentação OpenAPI interativa fica em `/docs` (schema em
`/openapi.json`), então dá para testar as rotas pelo navegador.

A autenticação **é obrigatória e só aceita Bearer**: todas as rotas exceto
`/health` exigem `Authorization: Bearer <REST_API_KEY>`. Sem `REST_API_KEY`
configurada, as rotas protegidas respondem `503` — a API nunca roda aberta.

### Executando um turno

`POST /runs` aceita JSON (arquivos inline em base64) ou
`multipart/form-data` (uploads reais).

```bash
curl -s http://localhost:3000/runs \
  -H "Authorization: Bearer $REST_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"message": "O que é o Harness?", "user_id": "u1", "session_id": "s1"}'
```

```json
{"run_id": "run_…", "session_id": "s1", "user_id": "u1", "content": "…",
 "images": [], "audio": [], "videos": [], "files": []}
```

Quando `session_id` é omitido, ele é gerado (`rest:<user_id>:<aleatório>`) e
devolvido na resposta; `user_id` assume `rest:anonymous`. Mídia gerada volta
em base64 (`base64`) ou como `url`, quando o agente produziu um link.

### Arquivos

Em JSON, os arquivos vão em `files`, com `data` em base64 (payload puro ou
`data:` URL) ou `url` para o agente buscar:

```bash
curl -s http://localhost:3000/runs \
  -H "Authorization: Bearer $REST_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"message": "leia isto", "files": [
        {"name": "foto.png", "mime_type": "image/png", "data": "iVBORw0…"}
      ]}'
```

Em multipart, use o campo `files` (tipo inferido) ou declare o tipo no nome do
campo — `images`, `audio`, `videos`, `documents`:

```bash
curl -s http://localhost:3000/runs \
  -H "Authorization: Bearer $REST_API_KEY" \
  -F 'message=descreva isto' \
  -F 'images=@foto.png' \
  -F 'documents=@relatorio.pdf'
```

`files_metadata` (string JSON no multipart, lista ou objeto com nome como
chave no JSON) sobrescreve a classificação de cada arquivo:

```json
[{"name": "relatorio.pdf", "type": "document", "mime_type": "application/pdf"}]
```

Limites: `REST_MAX_FILES` (padrão 10) e `REST_MAX_FILE_BYTES` (padrão 25 MB)
— exceder qualquer um retorna `413`.

### Sessões

`GET /sessions/{session_id}/session` devolve `user_id`, `session_state`, o
histórico `runs` e o último `interaction_assessment`; use `?user_id=` para
restringir a busca. `404` quando não existe, `503` quando o app não tem
armazenamento de sessão.

`POST /sessions/{session_id}/session` é um upsert com merge parcial:
`session_state` é mesclado em profundidade, `runs` e `interaction_assessment`
substituem o valor armazenado quando presentes, e `user_id` só é obrigatório
para criar uma sessão nova. As escritas passam pela mesma sanitização de
guardrails usada pelo pipeline antes de persistir.

```bash
curl -s -X POST http://localhost:3000/sessions/s1/session \
  -H "Authorization: Bearer $REST_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"user_id": "u1", "session_state": {"user_persona": {"name": "Ana"}}}'
```

| Variável | Finalidade |
|---|---|
| `REST_API_KEY` | **Obrigatória.** Chave Bearer para todas as rotas exceto `/health` |
| `REST_MAX_FILES` | Arquivos por requisição (padrão 10) |
| `REST_MAX_FILE_BYTES` | Limite por arquivo (padrão 25 MB) |

## Adicionando uma interface

Uma interface é uma fábrica de roteador FastAPI que mora em
`semente/api/interfaces/`. Há dois jeitos de adicionar:

```python
from semente.api import SementeApp
from semente.api.interfaces import HTTP_INTERFACES

# 1. registre a fábrica: montada quando `channels` inclui o nome
HTTP_INTERFACES["metrics"] = lambda harness, manifest: Metrics(harness=harness)

# 2. ou monte uma interface avulsa em um app
semente_app = SementeApp("semente.yaml")
semente_app.build_app()          # instância FastAPI + interfaces padrão
semente_app.register("metrics", Metrics(harness=semente_app.harness))
```

Nos dois casos ela precisa de ``get_router()`` devolvendo um ``APIRouter``. A
REST é sempre montada; as demais seguem a lista `channels` do manifesto.
Interfaces que não servem HTTP (Streamlit, MCP) rodam em processo próprio e
aparecem em `semente/api/interfaces/__init__.py` em `CLI_INTERFACES`.
