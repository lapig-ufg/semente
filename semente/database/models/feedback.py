"""Feedback models (negative, positive, and analysis feedback)."""

from sqlalchemy import Column, Integer, Text, JSON

from semente.database.session import Base


class NegativeFeedback(Base):
    __tablename__ = 'negative_feedbacks'

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(Text)
    payload = Column(JSON, comment=(
        "Par DPO (prompt, rejected, chosen, approved)"
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
    trajectory = Column(JSON, comment="Trajetória sanitizada para SFT (messages)")


class AnalysisFeedback(Base):
    __tablename__ = 'analysis_feedbacks'

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(Text)
    original_question = Column(Text)
    desired_analysis = Column(Text)
    history = Column(JSON, comment=(
        "Últimas 3 rodadas da conversa (tuples user/assistant)"
    ))