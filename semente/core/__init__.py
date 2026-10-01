"""Semente core — the engine-free agent pipeline.

External interface:
    Semente      -- the single-object pipeline the channels call.
    get_agent     -- manifest + domain + prompts loading, cached singleton.
    StepOutput    -- the run response envelope (content, media, metrics).
    AgentSession  -- per-(user, session) state and history record.
    SessionStore  -- SQLAlchemy-backed session persistence.
"""

from semente.core.semente_agent import Semente, get_agent
from semente.core.types import AgentSession, SessionStore, StepOutput

__all__ = [
    "Semente",
    "get_agent",
    "StepOutput",
    "AgentSession",
    "SessionStore",
]