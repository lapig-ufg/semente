"""Agno media conversion — Semente-native <-> Agno, shared by the tool layer
and the agent adapter so there is exactly one converter.
"""

from __future__ import annotations

from typing import Any

from agno.media import Audio as EAudio
from agno.media import File as EFile
from agno.media import Image as EImage
from agno.media import Video as EVideo
from agno.tools.function import ToolResult as EToolResult

from semente.tools.types import ToolResult


def to_engine_media(obj: Any, engine_cls: type) -> Any:
    """Convert one Semente media dataclass to the engine's media type."""
    if obj is None or isinstance(obj, engine_cls):
        return obj
    fields = {k: v for k, v in vars(obj).items() if v is not None}
    try:
        return engine_cls(**fields)
    except Exception:
        # Engine media models validate fields (e.g. agno File only accepts a
        # mime whitelist — zip/rar/kmz/kml are rejected). Retry without
        # optional descriptors so the raw bytes survive; formats can be
        # detected from the filename instead (mirrors the legacy intake).
        for drop in ("mime_type", "format", "file_type", "detail"):
            if drop in fields:
                fields.pop(drop)
                try:
                    return engine_cls(**fields)
                except Exception:
                    continue
        raise


def to_engine_result(result: Any) -> Any:
    """Convert a Semente ToolResult to the engine's ToolResult; pass others through."""
    if not isinstance(result, ToolResult):
        return result

    return EToolResult(
        content=result.content,
        images=[to_engine_media(i, EImage) for i in result.images] if result.images else None,
        videos=[to_engine_media(v, EVideo) for v in result.videos] if result.videos else None,
        audios=[to_engine_media(a, EAudio) for a in result.audios] if result.audios else None,
        files=[to_engine_media(f, EFile) for f in result.files] if result.files else None,
    )
