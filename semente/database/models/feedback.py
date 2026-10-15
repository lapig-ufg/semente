"""Feedback models (negative, positive, and analysis feedback)."""

from sqlalchemy import Column, Integer, Text, JSON

from semente.database.session import Base


class NegativeFeedback(Base):
    __tablename__ = 'negative_feedbacks'

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(Text)
    original_question = Column(Text)
    reason_frustration = Column(Text)
    desired_answer = Column(Text)
    context = Column(Text)
    payload = Column(JSON, comment="Trajetória sanitizada para DPO (prompt, chosen, rejected)")


class PositiveFeedback(Base):
    __tablename__ = 'positive_feedbacks'

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(Text)
    user_message = Column(Text)
    assistant_response = Column(Text)
    handler_message = Column(Text)
    grade = Column(Integer)
    context = Column(Text)
    trajectory = Column(JSON, comment="Trajetória sanitizada para SFT (messages)")


class AnalysisFeedback(Base):
    __tablename__ = 'analysis_feedbacks'

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(Text)
    original_question = Column(Text)
    desired_analysis = Column(Text)
    context = Column(Text)