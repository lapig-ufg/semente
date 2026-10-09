from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, Field

class MessageRow(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_call_id: Optional[str] = None

class SFTDatasetRow(BaseModel):
    messages: List[MessageRow] = Field(..., min_length=1)

class DPODatasetRow(BaseModel):
    prompt: Union[str, List[MessageRow]]
    chosen: Union[str, List[MessageRow]]
    rejected: Union[str, List[MessageRow]]