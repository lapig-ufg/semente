"""Per-turn assessment of the interaction quality (satisfaction).

Stored as a typed property on ``Session`` (``interaction_assessment``) and
persisted in its own JSON column on ``SessionRecord`` — never inside
``session_state``. The pending DPO pair also lives here (``pending``), so
EVERYTHING related to the interaction assessment travels in one object.
"""

from typing import Optional
from pydantic import BaseModel, Field


class Effectiveness(BaseModel):
    level: int = Field(
        description="Nível de satisfação do usuário (1 a 5, onde 1 é muito frustrado e 5 é muito satisfeito)",
        ge=1,
        le=5
    )
    level_message: str = Field(
        description="Mensagem descritiva ou justificativa do nível de satisfação (ex: 'Usuário demonstrou ironia e insatisfação com a resposta anterior')"
    )
    changed_topic: bool = Field(
        default=False,
        description=(
            "True quando o usuário abandonou o assunto da última resposta e está "
            "falando de um tema diferente; False quando ele continua no mesmo tópico"
        ),
    )


class PendingFeedback(BaseModel):
    """The open DPO pair, from the frustration turn until the evaluation turn.

    - ``record_id``: id of the ``NegativeFeedback`` row inserted when the
      frustration was registered (it already holds ``prompt`` + ``rejected``;
      ``chosen`` is still empty).
    - ``new_response``: the replacement answer the agent generated this turn
      (captured before the apology is prepended). Next turn, when the user's
      evaluation comes back positive, this text is written as ``chosen`` on
      the stored row; otherwise the pending is dropped and the row stays
      open with ``chosen`` empty.
    """

    record_id: int = Field(
        description="Id da linha NegativeFeedback aberta (prompt + rejected)."
    )
    new_response: str = Field(
        default="",
        description="Nova resposta gerada pelo agente no turno da frustração.",
    )


class InteractionAssessment(BaseModel):
    """How the interaction went, from the user's last message."""
    satisfaction: Effectiveness = Field(
        description="Estado de satisfação e humor geral do usuário no momento atual"
    )
    pending: Optional[PendingFeedback] = Field(
        default=None,
        description=(
            "Par DPO em aberto, quando o usuário ficou frustrado no turno "
            "anterior e esta mensagem é a avaliação da nova resposta"
        ),
    )