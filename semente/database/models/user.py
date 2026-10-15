"""User identity models."""

import datetime
from sqlalchemy import Column, String, DateTime, Boolean

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