# Guardrails

Guardrails de entrada inspecionam a entrada bruta do usuário em um turno e
**ocultam** dados sensíveis (mantendo o resto do pedido) ou **bloqueiam** o turno
com uma resposta ao usuário. São **plugáveis e opt-in**: um app declara seus
guards no `DomainSpec`, e o framework executa a mesma cadeia em todo lugar onde a
entrada pode vazar — o pipeline, os canais, o texto derivado de mídia e a camada
de persistência.

> **A privacidade é guiada por declaração.** Um app sem `guardrails` no seu
> `DomainSpec` não oculta nada. Declare apenas o que cabe à sua jurisdição e
> domínio — o framework traz guards universais (e-mail, cartão de crédito) e
> fica fora de especificidades de país/documento.

## Declarando guardrails

```python
from semente import EmailGuardrail
from semente.domain import DomainSpec

domain_spec = DomainSpec(
    name="My App",
    tools=[...],
    guardrails=[EmailGuardrail(), CardGuardrail()],
)
```

A cadeia é composta uma vez pelo harness (`get_harness`) e reutilizada em:

| Etapa | O que a cadeia faz |
|---|---|
| Pipeline (`source="pipeline"`) | Oculta o texto consolidado do turno (incluindo transcrições de mídia mescladas depois pelo `_input_preprocessing` — essas rodam primeiro, `source="media"`, então nada bruto é persistido) |
| Portas dos canais (`source="channel"`) | O `MessageContent` do WhatsApp oculta/mascara **antes** que o texto bruto alcance os logs do próprio roteador, o cache de debounce do Valkey ou o banco de dados. O webapp Streamlit exibe intencionalmente a **entrada bruta completa** — é a interface de desenvolvimento, o eco do próprio usuário não é uma superfície de vazamento, e o `run()` protege tudo a jusante |
| Persistência | As linhas de feedback DPO/SFT são sanitizadas campo a campo (`sanitize_json`) |
| Logs | Todo guard pode fornecer um `mask()` — as linhas de log mantêm a forma e descartam os valores |

O interruptor de feature `guardrails` no manifesto (padrão `true`) desliga toda a
cadeia se um dia você precisar (`features.guardrails: false`); a chave legada
`pii_guardrail` ainda é aceita com um aviso de depreciação.

## Escrevendo os seus

O framework é deliberadamente plano — sem registro de plugins, sem hierarquia de
interfaces. Implemente o protocolo de dois atributos (ou herde de
`RegexGuardrail` para o caso comum de regex):

### Guardrails de regex (subclasse)

```python
import re
from semente.guardrails import RegexGuardrail

class PhoneGuardrail(RegexGuardrail):
    name = "phone"                    # identificador seguro para logs
    marker = "[PHONE_HIDDEN]"         # escrito no texto
    patterns = (
        re.compile(r"(?<!\d)\d{2}[ -]\d{4,5}[ -]?\d{4}(?!\d)"),
    )
    # opcional, alinhado com patterns: validadores recebem o texto da
    # correspondência; retornar False a mantém (filtragem por dígito verificador)
```

O `redact` substitui cada correspondência validada pelo marcador e reporta
`removed: ["phone"]`; o `mask` cobre além do necessário para logs, sem
validadores.

### Guards de bloqueio

Retorne um resultado `blocked` para recusar o turno por completo — o agente
nunca executa e o usuário recebe `response`:

```python
from semente.guardrails import GuardrailContext, GuardrailResult, RegexGuardrail

class SecretsGuardrail(RegexGuardrail):
    name = "secrets"
    marker = "[X]"

    def redact(self, context: GuardrailContext) -> GuardrailResult:
        match = _SECRET_RE.search(context.text)
        if match:
            return GuardrailResult(
                text=context.text,
                blocked=True,
                response="Por segurança, não posso processar mensagens com credenciais.",
            )
        return super().redact(context)
```

### Guards funcionais (duck typing)

Qualquer objeto com `name` e `redact(context) -> GuardrailResult` satisfaz o
protocolo — sem necessidade de herança.

## Guardrails embutidos

Guard | Import | Comportamento
---|---|---
`EmailGuardrail` | `from semente.guardrails import EmailGuardrail` | Oculta endereços de e-mail (baseado em formato)
`CardGuardrail` | `from semente.guardrails import CardGuardrail` | Oculta números de cartão (agrupados ou com prefixo de bandeira, validados por Luhn); números soltos de 13–16 dígitos são intencionalmente ignorados — 1 em 9 passa no Luhn por acaso

## GuardrailContext e GuardrailResult

```python
from semente.guardrails import GuardrailContext, GuardrailResult

@dataclass
class GuardrailContext:
    text: str                   # reescrito pelos guards anteriores da cadeia
    session_state: dict | None
    user_id: str | None
    source: str                 # "channel" | "media" | "pipeline" | "tool"

@dataclass
class GuardrailResult:
    text: str                   # entregue ao próximo guard/etapa
    removed: list[str]          # apenas tipos — os logs nunca veem valores
    blocked: bool
    response: str | None        # a recusa ao usuário quando bloqueado
```

## O conjunto Brasil/LGPD

Os guards originais do framework (CPF, CNPJ, RG, proteção do CAR, camada de
intenção pt-BR) foram **extraídos do Semente** para o seu projeto de origem —
veja `migrate-to-pasto-legal/` e [Pasto Legal](/pt/showcase/pasto-legal) para ver
como um domínio reintroduz detectores específicos de país com esta interface.

## Depuração

Cada etapa registra seu resultado — **só tipos, nunca valores** — para que você
acompanhe o ciclo de vida dos guardrails no terminal (INFO fica ligado em todo
ambiente; o detalhe por guard exige `APP_ENV=development`, onde
`DEBUG_MODE=True`):

```
guardrail 'email': clean                                   (debug, per guard)
guardrail 'phone': redacted (phone)                        (info, per guard hit)
guardrail 'credentials': BLOCKED the turn [source=pipeline] (info)
guardrails[channel:whatsapp]: removed (phone, email)        (info, channel door)
guardrails[media:audio]: removed (email)                    (info, media-derived text)
guardrails[pipeline]: 3 guard(s) ran — clean                (info, once per turn)
guardrails[pipeline]: removed (phone)                       (info)
guardrails[pipeline]: BLOCKED by (credentials) — agent skipped, refusal reply sent
guardrails[persistence]: sensitive spans redacted before persistence  (debug)
```

As tags de etapa dizem onde rodou: `channel` (porta do whatsapp/streamlit),
`media`, `pipeline`, `persistence`. A cadeia no estado da sessão do painel de
depuração do Streamlit também traz os tipos removidos do turno.
