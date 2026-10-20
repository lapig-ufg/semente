"""Feedback models (negative, positive, and analysis feedback)."""

from sqlalchemy import Boolean, Column, Integer, Text, JSON

from semente.database.session import Base


class NegativeFeedback(Base):
    __tablename__ = 'negative_feedbacks'

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(Text)
    prompt = Column(Text, comment="User message that produced the rejected answer")
    rejected = Column(Text, comment="Answer rated as bad (DPO data)")
    chosen = Column(Text, default="", comment=(
        "Corrected answer, written when the remediation evaluation is "
        "positive (approved=True); stays empty while the pair is open"
    ))
    approved = Column(Boolean, comment=(
        "Outcome of the remediation evaluation: True (DPO pair valid for "
        "training) or False (remediation failed, analysis only); empty while "
        "not yet evaluated"
    ))
    rejected_new = Column(Text, comment=(
        "Corrected answer rejected by the user (remediation failed; "
        "useful only for manual analysis)"
    ))
    history = Column(JSON, comment=(
        "Last 3 rounds of the frustration cycle (user/assistant tuples), "
        "starting from the moment the frustration was detected"
    ))


class PositiveFeedback(Base):
    __tablename__ = 'positive_feedbacks'

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(Text)
    grade = Column(Integer)
    history = Column(JSON, comment=(
        "Clean rounds (user/assistant tuples) from the satisfying moment, "
        "for the SFT dataset"
    ))


class AnalysisFeedback(Base):
    __tablename__ = 'analysis_feedbacks'

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(Text)
    original_question = Column(Text)
    desired_analysis = Column(Text)
    history = Column(JSON, comment=(
        "Last 3 rounds of the conversation (user/assistant tuples)"
    ))