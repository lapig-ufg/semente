# Canais

O Semente traz três canais: **WhatsApp** (produção, para usuários finais),
**Streamlit** (desenvolvimento, para depuração) e **A2A** (agente-para-agente).
Todos executam o mesmo Harness.

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
from semente.build import build_app

app = build_app("semente.yaml")

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

## Adicionando um canal

Canais são fábricas de roteadores FastAPI conectadas em
`semente.build.build_app`. Para adicionar um, implemente o roteador e registre-o
em `build_app` com base na lista `channels` do manifesto.
