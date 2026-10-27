# Feedback e Fine-Tuning

O recurso `interaction-assessment` transforma conversas comuns em dados de
treinamento. Ele roda a cada turno (quando habilitado), avalia a satisfação do
usuário, persiste os resultados no banco de dados e captura trajetórias DPO e
SFT — tudo neutro quanto ao domínio e conduzido pelo harness, não pelas suas
ferramentas.

Um único interruptor cobre tanto o comportamento quanto a captura de dados:

```yaml
# semente.yaml
features:
  interaction-assessment:
    enable: true                   # todo o ciclo abaixo (padrão true)
    window_size: 5                 # janela deslizante de trajetória SFT (padrão 5, mín. 1)
```

Também aceita um booleano simples (`interaction-assessment: false`), que se
expande para `{enable: <bool>, window_size: 5}`.

> **Chaves legadas:** os antigos interruptores `feedback_workflow` e `feedback`
> ainda carregam (mesclados em `interaction-assessment`, com avisos de
> depreciação) — renomeie-os no seu manifesto. Com apenas chaves legadas,
> `feedback: false` desabilita o recurso como antes.

## O agente de satisfação

Com `interaction-assessment` ligado, a cada turno fora do onboarding o **agente
de avaliação de satisfação** lê a última troca mais a mensagem atual e retorna
um `Effectiveness` estruturado (`semente/schemas/interaction_assessment.py`):

- `level` — satisfação de 1 a 5 (≤ 2 insatisfeito, ≥ 4 satisfeito)
- `changed_topic` — se o usuário saiu da resposta que falhou

Isso é uma chamada extra ao LLM por turno; defina
`interaction-assessment: false` para ignorá-la por completo. Desabilitá-lo
também desabilita as etapas de persistência seguintes.

## O ciclo DPO em duas fases

Turnos insatisfatórios abrem um **ciclo de remediação** capturado em exatamente
dois turnos em uma linha `NegativeFeedback` (`semente/database/models/feedback.py`):

| Turno | O que acontece | Estado da linha |
|---|---|---|
| **n** (level ≤ 2, sem mudança de tópico) | O harness guarda a resposta rejeitada (`prompt` + `rejected`), responde com uma resposta de **remediação** no lugar da saída bruta do agente e marca `assessment.pending` com o id da linha | `chosen` vazio, par aberto |
| **n + 1** (o usuário avalia a remediação) | Positivo (level ≥ 4) completa a metade `chosen` da linha com `approved: true`; negativo (level ≤ 2) registra `approved: false` + `rejected_new` (mantido para análise manual, **não** para treinamento) | par fechado, `history` gravado |

Regras:

- Um ciclo nunca reabre no turno de fechamento — um usuário ainda frustrado abre
  um ciclo *novo* um turno depois.
- `_finalize_pending_history` (depois que a execução é anexada) grava o
  `history` do ciclo na linha e limpa o pendente, de modo que uma falha entre
  turnos deixa um pendente reexecutável em vez de um estado quebrado.

## O ramo SFT

Com `interaction-assessment.enable` ligado, execuções limpas do agente anexam sua
trajetória a `session_state["recent_agent_runs"]`. Turnos de onboarding e de
ciclo de remediação **nunca** são gravados — apenas trocas limpas e funcionais,
limitadas às `window_size` execuções mais recentes. Quando um turno positivo
dispara, a janela é persistida como uma linha `PositiveFeedback`, com PII
mascarada, seguindo os schemas `SFTDatasetRow` / `DPODatasetRow` em
`semente/schemas/fine_tuning.py`:

```python
class MessageRow(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: Optional[str] = None
    tool_calls: ...
    tool_call_id: ...

class SFTDatasetRow(BaseModel):
    messages: List[MessageRow]

class DPODatasetRow(BaseModel):
    prompt: str | List[MessageRow]
    chosen: str | List[MessageRow]
    rejected: str | List[MessageRow]
```

> As linhas hoje vivem somente nessas tabelas — um exportador de datasets ainda
> não faz parte do pacote; os schemas definem o formato alvo.

## Onde isso roda no pipeline

```
├── _summarize_conversation        # a cada 6 turnos (com interaction-assessment desligado ainda roda)
├── _process_feedback              # controlado por interaction-assessment
│   ├── _evaluate_satisfaction     # Effectiveness estruturado
│   ├── _persist_feedback          # DPO em duas fases / janelas SFT
│   └── _manage_persona            # agente de persona (PersonaUpdate)
├── _run_single_agent              # grava trajetória só com interaction-assessment.enable
│   └── _generate_apology          # sobrescreve a saída quando há um ciclo aberto
```

Veja a página de [Arquitetura](/pt/architecture/) para saber onde isso se
encaixa no pipeline completo de um turno. As trajetórias persistidas são
sanitizadas campo a campo pela [cadeia de guardrails](/pt/guide/guardrails) do
app antes do armazenamento.
