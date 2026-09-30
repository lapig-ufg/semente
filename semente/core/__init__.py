"""Semente core — the engine-free agent pipeline.

External interface:
    SementeAgent  -- the single-object pipeline the channels call.
    get_agent     -- manifest + domain + prompts loading, cached singleton.
    StepOutput    -- the run response envelope (content, media, metrics).
    AgentSession  -- per-(user, session) state and history record.
    SessionStore  -- SQLAlchemy-backed session persistence.
"""

from semente.core.semente_agent import SementeAgent, get_agent
from semente.core.types import AgentSession, SessionStore, StepOutput

__all__ = [
    "SementeAgent",
    "get_agent",
    "StepOutput",
    "AgentSession",
    "SessionStore",
]