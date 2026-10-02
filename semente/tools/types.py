"""Engine-neutral media and tool-result types.

Semente-native dataclasses that mirror the engine's shapes. Domains construct
these; the backend adapters convert them to the engine's equivalents at the
boundary. Field names intentionally match the engine's so conversion is a
field-by-field copy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Union


@dataclass
class Image:
    url: Optional[str] = None
    filepath: Optional[Union[Path, str]] = None
    content: Optional[bytes] = None
    id: Optional[str] = None
    format: Optional[str] = None
    mime_type: Optional[str] = None
    detail: Optional[str] = None
    original_prompt: Optional[str] = None
    revised_prompt: Optional[str] = None
    alt_text: Optional[str] = None


@dataclass
class Video:
    url: Optional[str] = None
    filepath: Optional[Union[Path, str]] = None
    content: Optional[bytes] = None
    id: Optional[str] = None
    format: Optional[str] = None
    mime_type: Optional[str] = None
    duration: Optional[float] = None
    width: Optional[int] = None
    height: Optional[int] = None
    fps: Optional[float] = None


@dataclass
class File:
    id: Optional[str] = None
    url: Optional[str] = None
    filepath: Optional[Union[Path, str]] = None
    content: Optional[bytes] = None
    mime_type: Optional[str] = None
    file_type: Optional[str] = None
    filename: Optional[str] = None
    size: Optional[int] = None
    format: Optional[str] = None
    name: Optional[str] = None


@dataclass
class Audio:
    url: Optional[str] = None
    filepath: Optional[Union[Path, str]] = None
    content: Optional[bytes] = None
    id: Optional[str] = None
    format: Optional[str] = None
    mime_type: Optional[str] = None
    duration: Optional[float] = None
    sample_rate: Optional[int] = None
    channels: Optional[int] = None
    transcript: Optional[str] = None
    ext: Optional[str] = None


@dataclass
class ToolResult:
    """Result from a domain tool, possibly carrying media artifacts."""

    content: str
    images: Optional[list[Image]] = None
    videos: Optional[list[Video]] = None
    audios: Optional[list[Audio]] = None
    files: Optional[list[File]] = None


@dataclass
class Tool:
    """A Semente-native tool: the raw function plus its declaration metadata.

    Engine-neutral — backends convert this to their own tool type (agno
    ``Function``, ADK function, Gemini ``FunctionDeclaration``). ``__call__``
    delegates to the raw function so a decorated tool can still be invoked
    directly in tests.
    """

    name: str
    func: Callable
    description: str = ""
    tool_hooks: list[Callable] = field(default_factory=list)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self.func(*args, **kwargs)
