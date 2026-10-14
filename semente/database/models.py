import datetime
from sqlalchemy import Column, Integer, Text, String, DateTime, Boolean, JSON

from semente.database.session import Base

class UserTermsAcceptance(Base):
    """Table that records the formal acceptance of the system's terms and conditions."""
    __tablename__ = "user_terms_acceptance"
    
    user_id = Column(String, primary_key=True, index=True, comment="Unique identifier (e.g., wa:5511999999999)")
    accepted = Column(Boolean, default=False, nullable=False, comment="Flag indicating acceptance")
    accepted_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False, comment="Date and time of formal acceptance")
    

class UserProfile(Base):
    """Table that stores the identification profile captured during onboarding."""
    __tablename__ = "user_profile"

    user_id = Column(String, primary_key=True, index=True, comment="Unique identifier (e.g., wa:5511999999999)")
    name = Column(String, nullable=True, comment="User's given name")
    role = Column(String, nullable=True, comment="User's professional role")
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow, nullable=False)
    
class UserTutorialProgress(Base):
    """Table that records the final tutorial outcome of a user.

    Only the final outcome is persisted (one row per user): the user declined
    the tutorial offer, left the tutorial early, or completed all its steps.
    Everything in between lives in the session state only, so a user who is
    mid-tutorial — or was never offered it — simply has no row here.
    """
    __tablename__ = "user_tutorial_progress"

    user_id = Column(String, primary_key=True, index=True, comment="Unique identifier (e.g., wa:5511999999999)")
    completed = Column(Boolean, default=True, nullable=False, comment="Flag indicating the tutorial reached its final state (declined or completed)")
    completed_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False, comment="Date and time of the final state")


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


class WorkflowSessionRecord(Base):
    """Canonical workflow session: state + history pairs per (user, session)."""
    __tablename__ = 'workflow_sessions'

    session_id = Column(String, primary_key=True, index=True)
    user_id = Column(String, index=True)
    session_state = Column(JSON, default=dict)
    runs = Column(JSON, default=list)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


