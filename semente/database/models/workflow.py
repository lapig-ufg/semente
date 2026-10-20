"""Workflow persistence models."""

import datetime
from sqlalchemy import Column, String, DateTime, JSON

from semente.database.session import Base


class SessionRecord(Base):
    """Canonical workflow session: state + history pairs per (user, session)."""
    __tablename__ = 'workflow_sessions'

    session_id = Column(String, primary_key=True, index=True)
    user_id = Column(String, index=True)
    session_state = Column(JSON, default=dict)
    runs = Column(JSON, default=list)
    interaction_assessment = Column(JSON, nullable=True, comment="Assessment of the last round's interaction (satisfaction + remediation)")
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)