"""Semente core — the engine-free agent pipeline.

External interface:
    Harness  -- the single-object pipeline the channels call.
    get_harness     -- manifest + domain + prompts loading, cached singleton.
    StepOutput    -- the run response envelope (content, media, metrics).
    AgentSession  -- per-(user, session) state and history record.
    SessionStore  -- SQLAlchemy-backed session persistence.
"""

from semente.core.harness import Harness, get_harness
from semente.core.types import Session, SessionStore, StepOutput

__all__ = [
    "Harness",
    "get_harness",
    "StepOutput",
    "Session",
    "SessionStore",
]