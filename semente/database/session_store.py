"""Canonical agent session store (Semente-owned, engine-free)."""

from semente.core.types import SessionStore
from semente.database.models import SessionRecord
from semente.database.session import SessionLocal, engine

# Ensure the table exists (idempotent).
SessionRecord.metadata.create_all(bind=engine)

store = SessionStore(SessionLocal, SessionRecord)