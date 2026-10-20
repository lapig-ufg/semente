from typing import Optional
from pydantic import BaseModel, Field


class InputManager(BaseModel):
    summary: Optional[str] = Field(
        default=None,
        description="Accumulated summary of the conversation context."
    )
    runs_count: int = Field(
        default=0,
        description="Counter of runs since the last summary."
    )