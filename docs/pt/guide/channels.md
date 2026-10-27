# Canais

O Semente traz dois canais: **WhatsApp** (produção, para usuários finais) e
**Streamlit** (desenvolvimento, para depuração). Ambos executam o mesmo Harness.

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

## Adicionando um canal

Canais são fábricas de roteadores FastAPI conectadas em
`semente.build.build_app`. Para adicionar um, implemente o roteador e registre-o
em `build_app` com base na lista `channels` do manifesto.
