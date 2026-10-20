"""Feedback models (negative, positive, and analysis feedback)."""

from sqlalchemy import Boolean, Column, Integer, Text, JSON

from semente.database.session import Base


class NegativeFeedback(Base):
    __tablename__ = 'negative_feedbacks'

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(Text)
    prompt = Column(Text, comment="Mensagem do usuário geradora da resposta rejeitada")
    rejected = Column(Text, comment="Resposta avaliada como ruim (dado DPO)")
    chosen = Column(Text, default="", comment=(
        "Resposta corrigida, escrita quando a avaliação da remediação é "
        "positiva (approved=True); fica vazia enquanto o par está aberto"
    ))
    approved = Column(Boolean, comment=(
        "Resultado da avaliação da remediação: True (par DPO válido para "
        "treino) ou False (remediação falhou, só análise); vazio enquanto "
        "não avaliado"
    ))
    rejected_new = Column(Text, comment=(
        "Resposta corrigida rejeitada pelo usuário (remediação falhou; "
        "útil apenas para análise manual)"
    ))
    history = Column(JSON, comment=(
        "Últimas 3 rodadas do ciclo de frustração (tuples user/assistant), "
        "a partir do momento em que a frustração foi detectada"
    ))


class PositiveFeedback(Base):
    __tablename__ = 'positive_feedbacks'

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(Text)
    grade = Column(Integer)
    history = Column(JSON, comment=(
        "Rodadas limpas (tuples user/assistant) do momento satisfatório, "
        "para o dataset SFT"
    ))


class AnalysisFeedback(Base):
    __tablename__ = 'analysis_feedbacks'

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(Text)
    original_question = Column(Text)
    desired_analysis = Column(Text)
    history = Column(JSON, comment=(
        "Últimas 3 rodadas da conversa (tuples user/assistant)"
    ))