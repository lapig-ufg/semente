"""Semente core data types — engine-free.

The plain value objects the Semente pipeline exchanges with channels
and persists to the database: the response envelope (``StepOutput``), the
per-(user, session) conversation record (``AgentSession``) and the
SQLAlchemy-backed persistence (``SessionStore``).

Historical note: ``StepOutput`` keeps its name for compatibility with the
channels (WhatsApp/Streamlit read ``response.content``, ``response.images``,
``response.audio``, ...) and with the Streamlit debug panel.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from semente.logging import log_error


@dataclass
class StepOutput:
    """The agent run response: content plus media and metrics."""
    content: str = ""
    images: Optional[list] = None
    videos: Optional[list] = None
    audio: Optional[list] = None
    files: Optional[list] = None
    metrics: Optional[dict] = None
    stop: bool = False
    success: bool = True
    steps: Optional[list["StepOutput"]] = None
    step_name: Optional[str] = None


@dataclass
class AgentSession:
    """Per-(user, session) conversation state and history.

    ``session_state`` is the mutable dict shared by every Semente
    method during a run and persisted between runs; ``runs`` is the
    conversation history as ``[{"user": ..., "assistant": ..., "ts": ...}]``.
    """
    user_id: str
    session_id: str
    session_state: dict = field(default_factory=dict)
    runs: list[dict] = field(default_factory=list)

    def get_history(self, num_runs: Optional[int] = None) -> list[tuple[str, str]]:
        """Return ``(user, assistant)`` pairs, oldest first."""
        runs = self.runs if num_runs is None else self.runs[-num_runs:]
        return [(r.get("user", ""), r.get("assistant", "")) for r in runs]


class SessionStore:
    """Canonical session persistence: state + history pairs per (user, session)."""

    def __init__(self, session_factory, model):
        self.session_factory = session_factory
        self.model = model

    def get(self, user_id: Optional[str], session_id: str) -> Optional[dict]:
        db = self.session_factory()
        try:
            query = db.query(self.model).filter(self.model.session_id == session_id)
            if user_id is not None:
                query = query.filter(self.model.user_id == user_id)
            record = query.first()
            if record is None:
                return None
            return {
                "session_state": record.session_state or {},
                "runs": record.runs or [],
            }
        finally:
            db.close()

    def save(self, user_id: str, session_id: str, session_state: dict, runs: list) -> None:
        db = self.session_factory()
        try:
            record = db.query(self.model).filter(
                self.model.session_id == session_id,
                self.model.user_id == user_id,
            ).first()
            if record is None:
                record = self.model(session_id=session_id, user_id=user_id)
                db.add(record)
            record.session_state = session_state
            record.runs = runs
            db.commit()
        except Exception as exc:
            db.rollback()
            log_error(f"SessionStore.save failed: {exc}")
        finally:
            db.close()

    def list_sessions(self, user_id: str) -> list[str]:
        """Return session ids for a user, most recently updated first."""
        db = self.session_factory()
        try:
            records = (
                db.query(self.model)
                .filter(self.model.user_id == user_id)
                .order_by(self.model.updated_at.desc())
                .all()
            )
            return [r.session_id for r in records]
        finally:
            db.close()