"""Request/response contracts for the REST channel.

Kept apart from the router so the OpenAPI schema reads as a document on its
own: every endpoint returns one of the models below and ``POST /runs``
accepts either :class:`RunRequest` (JSON) or its multipart equivalent
(documented in the route description).
"""

from __future__ import annotations

from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

#: What a file part may declare (and what the response groups media by).
MediaType = Literal["image", "audio", "video", "document"]


class RunFile(BaseModel):
    """One file in a JSON ``POST /runs`` body.

    Exactly one of ``data`` (base64, a plain payload or a ``data:`` URL) or
    ``url`` (fetched by the engine, not by Semente) is expected. ``type``
    overrides the classification inferred from ``mime_type``/``name``.
    """

    model_config = ConfigDict(extra="allow")

    name: Optional[str] = Field(default=None, description="Original filename.")
    mime_type: Optional[str] = Field(default=None, description="IANA media type.")
    type: Optional[MediaType] = Field(default=None, description="Explicit media type.")
    data: Optional[str] = Field(default=None, description="Base64 content (or data: URL).")
    url: Optional[str] = Field(default=None, description="Public URL for the engine to fetch.")


class RunFileMetadata(BaseModel):
    """Optional per-file hints: type override, mime type, display name.

    Entries are matched to files by ``name`` when both are set, and by
    position otherwise. Extra keys are accepted and ignored.
    """

    model_config = ConfigDict(extra="allow")

    name: Optional[str] = Field(default=None, description="Filename this entry describes.")
    mime_type: Optional[str] = None
    type: Optional[MediaType] = None
    description: Optional[str] = Field(default=None, description="Free-form note (passthrough).")


class RunRequest(BaseModel):
    """The JSON body of ``POST /runs`` (multipart carries the same fields)."""

    message: Optional[str] = Field(default=None, description="The user message (text).")
    session_id: Optional[str] = Field(
        default=None,
        description="Continue an existing session; a new one is generated when omitted.",
    )
    user_id: Optional[str] = Field(
        default=None, description="Owning user; defaults to 'rest:anonymous'."
    )
    files: list[RunFile] = Field(default_factory=list)
    files_metadata: Optional[
        Union[list[RunFileMetadata], dict[str, RunFileMetadata], str]
    ] = Field(
        default=None,
        description=(
            "Per-file hints, aligned by index/name (or keyed by filename). "
            "A JSON string is accepted too, mirroring the multipart field."
        ),
    )


class MediaOut(BaseModel):
    """One media item in a run response: inline base64 or a URL."""

    type: Literal["image", "audio", "video", "file"]
    mime_type: Optional[str] = None
    name: Optional[str] = None
    format: Optional[str] = None
    url: Optional[str] = None
    base64: Optional[str] = None


class RunResponse(BaseModel):
    """The result of one harness turn."""

    run_id: str
    session_id: str
    user_id: str
    content: str = ""
    images: list[MediaOut] = Field(default_factory=list)
    audio: list[MediaOut] = Field(default_factory=list)
    videos: list[MediaOut] = Field(default_factory=list)
    files: list[MediaOut] = Field(default_factory=list)


class HealthResponse(BaseModel):
    """Liveness probe — the only unauthenticated route."""

    status: Literal["ok"] = "ok"
    name: str
    version: str


class SessionResponse(BaseModel):
    """A persisted session: state, history and the latest assessment."""

    session_id: str
    user_id: Optional[str] = None
    session_state: dict[str, Any] = Field(default_factory=dict)
    runs: list[Any] = Field(default_factory=list)
    interaction_assessment: Optional[dict[str, Any]] = None


class SessionUpdate(BaseModel):
    """Body of ``POST /sessions/{session_id}/session`` — a partial update.

    ``session_state`` is deep-merged into the stored state; ``runs`` and
    ``interaction_assessment`` replace what is stored when present.
    ``user_id`` is required only when the session does not exist yet (it
    creates the row); existing sessions keep their owner.
    """

    user_id: Optional[str] = None
    session_state: Optional[dict[str, Any]] = None
    runs: Optional[list[Any]] = None
    interaction_assessment: Optional[dict[str, Any]] = None
