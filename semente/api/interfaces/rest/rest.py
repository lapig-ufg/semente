"""REST interface — run the Harness and read/write sessions over HTTP.

Four routes, all on the same ``Harness`` every other channel uses:

``POST /runs``
    One full conversation turn. Accepts ``application/json`` (files inline as
    base64) or ``multipart/form-data`` (real uploads); media is split into the
    engine-neutral ``Image``/``Audio``/``Video``/``File`` objects the harness
    already understands, and generated media comes back base64-encoded.

``GET /sessions/{session_id}/session``
    The persisted session: ``session_state``, conversation ``runs`` and the
    latest ``interaction_assessment``. ``?user_id=`` scopes the lookup.

``POST /sessions/{session_id}/session``
    Upsert with partial merge: ``session_state`` deep-merges, ``runs`` and
    ``interaction_assessment`` replace when present. Writes pass through the
    harness guardrail sanitization, like pipeline persistence.

``GET /health``
    Public liveness probe (the only route without authentication).

Auth is mandatory: every other route requires
``Authorization: Bearer <REST_API_KEY>``. When the key is not configured the
protected routes answer ``503`` — the API never falls back to open access.
"""

from __future__ import annotations

import base64
import binascii
import hmac
import json
import os
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from semente.core.types import SessionStore
from semente.api.interfaces.rest.schemas import (
    RunFileMetadata,
    HealthResponse,
    MediaOut,
    RunRequest,
    RunResponse,
    SessionResponse,
    SessionUpdate,
)
from semente.logging import log_error, log_info, log_warning
from semente.schemas.interaction_assessment import InteractionAssessment
from semente.tools.types import Audio, File, Image, Video

API_KEY_ENV = "REST_API_KEY"
DEFAULT_MAX_FILE_BYTES = 25 * 1024 * 1024
DEFAULT_MAX_FILES = 10
ANONYMOUS_USER = "rest:anonymous"

MEDIA_TYPES = ("image", "audio", "video", "document")

#: Extension → media type, used only when the mime type does not decide.
_EXTENSION_TYPES: dict[str, tuple[str, ...]] = {
    "image": (
        ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff", ".heic", ".avif",
    ),
    "audio": (".mp3", ".wav", ".ogg", ".oga", ".m4a", ".aac", ".flac", ".opus", ".amr"),
    "video": (".mp4", ".m4v", ".mov", ".avi", ".mkv", ".webm", ".3gp"),
}

#: Multipart field name → declared media type (``files`` is untyped).
_MULTIPART_FIELDS = {
    "files": None,
    "images": "image",
    "audio": "audio",
    "videos": "video",
    "documents": "document",
}


def _version() -> str:
    try:
        return metadata.version("semente-agents")
    except metadata.PackageNotFoundError:  # running from a source checkout
        return "0.0.0"


def _env_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, ""))
    except ValueError:
        return default
    return value if value > 0 else default


class _RESTError(HTTPException):
    """HTTPException raised by the channel's handlers (detail is JSON-safe)."""


@dataclass
class _IncomingFile:
    """A file as received from either transport, before classification."""

    name: Optional[str] = None
    mime_type: Optional[str] = None
    type: Optional[str] = None
    content: Optional[bytes] = None
    url: Optional[str] = None


def _openapi_request_body() -> dict[str, Any]:
    """Document both ``POST /runs`` transports in the OpenAPI schema.

    FastAPI only inspects declared parameters, and the route reads the body
    by hand (to accept JSON *and* multipart on the same path), so the body is
    attached explicitly. ``$defs`` are inlined: an operation-level schema
    cannot reference the document's component section.
    """

    def resolve(node: Any, defs: dict[str, Any]) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return resolve(defs[node["$ref"].rsplit("/", 1)[-1]], defs)
            return {key: resolve(value, defs) for key, value in node.items() if key != "$defs"}
        if isinstance(node, list):
            return [resolve(item, defs) for item in node]
        return node

    json_schema = RunRequest.model_json_schema()
    file_field = {"type": "array", "items": {"type": "string", "format": "binary"}}
    multipart = {
        "type": "object",
        "properties": {
            "message": {"type": "string"},
            "session_id": {"type": "string"},
            "user_id": {"type": "string"},
            "files_metadata": {
                "type": "string",
                "description": "JSON array or name-keyed object with per-file hints.",
            },
            **{field: dict(file_field) for field in _MULTIPART_FIELDS},
        },
    }
    return {
        "required": True,
        "content": {
            "application/json": {"schema": resolve(json_schema, json_schema.get("$defs", {}))},
            "multipart/form-data": {"schema": multipart},
        },
    }


def _infer_type(name: Optional[str], mime_type: Optional[str]) -> str:
    """Classify a file as image/audio/video/document."""
    mime = (mime_type or "").lower()
    for media_type in ("image", "audio", "video"):
        if mime.startswith(f"{media_type}/"):
            return media_type
    suffix = Path(name or "").suffix.lower()
    for media_type, extensions in _EXTENSION_TYPES.items():
        if suffix in extensions:
            return media_type
    return "document"


def _decode_base64(value: str, name: Optional[str]) -> bytes:
    """Decode a base64 payload (plain or ``data:`` URL) or fail with 400."""
    payload = value.strip()
    if payload.startswith("data:"):
        _, _, payload = payload.partition(",")
    try:
        return base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        label = f" '{name}'" if name else ""
        raise _RESTError(400, f"File{label} is not valid base64.")


def _deep_merge(base: dict, patch: dict) -> dict:
    """Recursively merge ``patch`` into ``base`` (patch wins on scalars)."""
    merged = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _metadata_entries(raw: Any) -> list[RunFileMetadata]:
    """Normalize ``files_metadata`` (JSON string, list or name-keyed dict)."""
    if raw is None or raw == "":
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raise _RESTError(400, "'files_metadata' must be valid JSON.")
    if isinstance(raw, dict):
        raw = [
            {"name": name, **value} if isinstance(value, dict) else {"name": name}
            for name, value in raw.items()
        ]
    if not isinstance(raw, list):
        raise _RESTError(400, "'files_metadata' must be a list or an object.")
    try:
        return [RunFileMetadata.model_validate(entry) for entry in raw]
    except ValidationError as exc:
        raise _RESTError(422, f"Invalid 'files_metadata': {exc.errors(include_url=False)}")


def _resolve_metadata(
    files: list[_IncomingFile], entries: list[RunFileMetadata]
) -> list[Optional[RunFileMetadata]]:
    """Match metadata by filename when possible, by position otherwise."""
    by_name = {entry.name: entry for entry in entries if entry.name}
    resolved: list[Optional[RunFileMetadata]] = []
    for index, file in enumerate(files):
        entry = by_name.get(file.name) if file.name else None
        if entry is None and index < len(entries) and not entries[index].name:
            entry = entries[index]
        resolved.append(entry)
    return resolved


def _session_response(session_id: str, record: dict) -> SessionResponse:
    """Shape a store record (or a freshly written one) as the API response."""
    assessment = record.get("interaction_assessment")
    if hasattr(assessment, "model_dump"):
        assessment = assessment.model_dump(mode="json")
    return SessionResponse(
        session_id=record.get("session_id") or session_id,
        user_id=record.get("user_id"),
        session_state=record.get("session_state") or {},
        runs=record.get("runs") or [],
        interaction_assessment=assessment or None,
    )


def _media_out(items: Optional[list], media_type: str) -> list[MediaOut]:
    """Encode generated media for JSON (base64 when the bytes are present)."""
    output: list[MediaOut] = []
    for item in items or []:
        content = getattr(item, "content", None)
        entry = MediaOut(
            type=media_type,
            mime_type=getattr(item, "mime_type", None),
            name=getattr(item, "name", None) or getattr(item, "filename", None),
            format=getattr(item, "format", None),
            url=getattr(item, "url", None),
        )
        if content:
            entry.base64 = base64.b64encode(content).decode("ascii")
        output.append(entry)
    return output


class REST:
    """Builds the FastAPI router that serves the app over a plain REST API.

    Args:
        agent: The ``Harness`` — anything with ``run(user_id=, session_id=,
            input=, images=, audio=, videos=, files=)``, a ``store`` and an
            optional ``sanitize``.
        name: Application name reported by ``GET /health``.
        api_key: Bearer key; defaults to ``REST_API_KEY``. There is no
            anonymous mode — without a key the protected routes answer 503.
        max_file_bytes: Per-file upload cap; defaults to
            ``REST_MAX_FILE_BYTES`` or 25 MB.
        max_files: Files-per-request cap; defaults to ``REST_MAX_FILES`` or 10.
    """

    def __init__(
        self,
        agent: Any,
        name: Optional[str] = None,
        api_key: Optional[str] = None,
        max_file_bytes: Optional[int] = None,
        max_files: Optional[int] = None,
    ) -> None:
        self.agent = agent
        self.name = name or getattr(agent, "name", "agent")
        self.api_key = api_key if api_key is not None else os.getenv(API_KEY_ENV) or None
        self.max_file_bytes = max_file_bytes or _env_int(
            "REST_MAX_FILE_BYTES", DEFAULT_MAX_FILE_BYTES
        )
        self.max_files = max_files or _env_int("REST_MAX_FILES", DEFAULT_MAX_FILES)
        if not self.api_key:
            log_warning(
                f"rest: {API_KEY_ENV} is not set — protected routes will answer 503 "
                "until a key is configured"
            )

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------
    def _require_auth(self, request: Request) -> None:
        """Bearer-only gate applied to every route except ``/health``."""
        if not self.api_key:
            log_error(f"rest: {API_KEY_ENV} is not configured — refusing the request")
            raise _RESTError(503, f"{API_KEY_ENV} is not configured on the server.")
        scheme, _, supplied = (request.headers.get("authorization") or "").partition(" ")
        if scheme.lower() != "bearer" or not supplied.strip():
            raise _RESTError(
                401,
                "Missing bearer token: send 'Authorization: Bearer <key>'.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if not hmac.compare_digest(supplied.strip().encode(), self.api_key.encode()):
            raise _RESTError(
                401,
                "Invalid bearer token.",
                headers={"WWW-Authenticate": "Bearer"},
            )

    # ------------------------------------------------------------------
    # POST /runs
    # ------------------------------------------------------------------
    async def create_run(self, request: Request) -> RunResponse:
        """Run one full conversation turn (JSON or multipart body)."""
        content_type = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
        if content_type == "multipart/form-data":
            message, session_id, user_id, files, metadata = await self._read_multipart(request)
        elif content_type in ("", "application/json"):
            message, session_id, user_id, files, metadata = await self._read_json(request)
        else:
            raise _RESTError(
                415,
                f"Unsupported content type '{content_type}': send application/json "
                "or multipart/form-data.",
            )

        if len(files) > self.max_files:
            raise _RESTError(
                413, f"Too many files ({len(files)}); the limit is {self.max_files}."
            )

        message = (message or "").strip()
        if not message and not files:
            raise _RESTError(400, "'message' is required when no file is sent.")

        entries = _metadata_entries(metadata)
        for file, entry in zip(files, _resolve_metadata(files, entries)):
            if file.content is not None and len(file.content) > self.max_file_bytes:
                raise _RESTError(
                    413,
                    f"File '{file.name or 'unnamed'}' exceeds the "
                    f"{self.max_file_bytes}-byte limit.",
                )
            file.type = (entry.type if entry else None) or file.type
            file.mime_type = (entry.mime_type if entry else None) or file.mime_type
            file.name = (entry.name if entry else None) or file.name

        user_id = user_id or ANONYMOUS_USER
        session_id = session_id or f"rest:{user_id}:{uuid4().hex[:8]}"
        run_id = f"run_{uuid4().hex}"

        kwargs = self._run_kwargs(message, files, user_id, session_id)
        log_info(f"rest: run {run_id} — session {session_id}, {len(files)} file(s)")
        try:
            output = await run_in_threadpool(self.agent.run, **kwargs)
        except Exception as exc:  # noqa: BLE001 — surfaced as a 500, never leaked
            log_error(f"rest: harness failed for run {run_id}: {exc}", exc_info=True)
            raise _RESTError(500, "The agent failed to process the request.")

        return RunResponse(
            run_id=run_id,
            session_id=session_id,
            user_id=user_id,
            content=getattr(output, "content", "") or "",
            images=_media_out(getattr(output, "images", None), "image"),
            audio=_media_out(getattr(output, "audio", None), "audio"),
            videos=_media_out(getattr(output, "videos", None), "video"),
            files=_media_out(getattr(output, "files", None), "file"),
        )

    async def _read_json(
        self, request: Request
    ) -> tuple[Optional[str], Optional[str], Optional[str], list[_IncomingFile], Any]:
        try:
            body = await request.json()
        except Exception:
            raise _RESTError(400, "The body is not valid JSON.")
        if not isinstance(body, dict):
            raise _RESTError(400, "The JSON body must be an object.")
        try:
            payload = RunRequest.model_validate(body)
        except ValidationError as exc:
            raise _RESTError(422, exc.errors(include_url=False))

        files: list[_IncomingFile] = []
        for spec in payload.files:
            if spec.data:
                content = _decode_base64(spec.data, spec.name)
            elif spec.url:
                content = None
            else:
                raise _RESTError(
                    400, f"File '{spec.name or 'unnamed'}' needs 'data' or 'url'."
                )
            files.append(
                _IncomingFile(
                    name=spec.name,
                    mime_type=spec.mime_type,
                    type=spec.type,
                    content=content,
                    url=spec.url,
                )
            )
        return payload.message, payload.session_id, payload.user_id, files, payload.files_metadata

    async def _read_multipart(
        self, request: Request
    ) -> tuple[Optional[str], Optional[str], Optional[str], list[_IncomingFile], Any]:
        form = await request.form()

        def _field(name: str) -> Optional[str]:
            value = form.get(name)
            return value.strip() or None if isinstance(value, str) else None

        files: list[_IncomingFile] = []
        for field_name, declared_type in _MULTIPART_FIELDS.items():
            for upload in form.getlist(field_name):
                if isinstance(upload, str):  # a text field, not a file part
                    continue
                files.append(
                    _IncomingFile(
                        name=upload.filename,
                        mime_type=upload.content_type,
                        type=declared_type,
                        content=await upload.read(),
                    )
                )
        return _field("message"), _field("session_id"), _field("user_id"), files, _field(
            "files_metadata"
        )

    def _run_kwargs(
        self, message: str, files: list[_IncomingFile], user_id: str, session_id: str
    ) -> dict[str, Any]:
        """Map received files onto the harness/engine media objects."""
        kwargs: dict[str, Any] = {"user_id": user_id, "session_id": session_id, "input": message}
        grouped: dict[str, list[Any]] = {"images": [], "audio": [], "videos": [], "files": []}
        for file in files:
            media_type = file.type or _infer_type(file.name, file.mime_type)
            if media_type == "image":
                grouped["images"].append(
                    Image(content=file.content, mime_type=file.mime_type, url=file.url)
                )
            elif media_type == "audio":
                grouped["audio"].append(
                    Audio(content=file.content, mime_type=file.mime_type, url=file.url)
                )
            elif media_type == "video":
                grouped["videos"].append(
                    Video(content=file.content, mime_type=file.mime_type, url=file.url)
                )
            else:
                grouped["files"].append(
                    File(
                        content=file.content,
                        mime_type=file.mime_type,
                        name=file.name,
                        url=file.url,
                    )
                )
        kwargs.update({key: items for key, items in grouped.items() if items})
        return kwargs

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------
    def _store(self) -> SessionStore:
        store = getattr(self.agent, "store", None)
        if store is None:
            raise _RESTError(503, "Session storage is not configured on the server.")
        return store

    @staticmethod
    def _load(store: SessionStore, user_id: Optional[str], session_id: str) -> Optional[dict]:
        """Read a session, preferring the identity-aware store method."""
        loader = getattr(store, "get_record", None) or store.get
        record = loader(user_id, session_id)
        if record is None:
            return None
        return {"session_id": session_id, "user_id": user_id, **record}

    async def get_session(
        self,
        session_id: str,
        user_id: Optional[str] = Query(default=None, description="Scope the lookup to one user."),
    ) -> SessionResponse:
        """Read one persisted session."""
        record = self._load(self._store(), user_id, session_id)
        if record is None:
            raise _RESTError(404, f"Session '{session_id}' was not found.")
        return _session_response(session_id, record)

    async def update_session(
        self,
        session_id: str,
        body: SessionUpdate,
        user_id: Optional[str] = Query(default=None, description="Scope the lookup to one user."),
    ) -> SessionResponse:
        """Upsert one session: deep-merge state, replace runs/assessment."""
        store = self._store()
        lookup_user = user_id if user_id is not None else body.user_id
        existing = self._load(store, lookup_user, session_id)
        if existing is None and lookup_user is not None:
            # The session may exist under another owner: session ids are the
            # primary key, so writing it as a "new" row would collide.
            if self._load(store, None, session_id) is not None:
                raise _RESTError(409, f"Session '{session_id}' belongs to another user.")

        if existing is None:
            owner = body.user_id or user_id
            if not owner:
                raise _RESTError(400, "user_id is required to create a session.")
            state = body.session_state or {}
            runs = body.runs or []
            assessment = self._assessment(body.interaction_assessment)
        else:
            owner = existing.get("user_id") or body.user_id or user_id
            if body.user_id and owner and body.user_id != owner:
                raise _RESTError(409, f"Session '{session_id}' belongs to another user.")
            state = _deep_merge(existing.get("session_state") or {}, body.session_state or {})
            runs = (
                list(body.runs) if body.runs is not None else existing.get("runs") or []
            )
            assessment = (
                self._assessment(body.interaction_assessment)
                if body.interaction_assessment is not None
                else existing.get("interaction_assessment")
            )

        sanitize = getattr(self.agent, "sanitize", None)
        if sanitize is not None:
            state = sanitize(state)
            runs = sanitize(runs)
            if assessment is not None:
                assessment = self._assessment(sanitize(assessment.model_dump(mode="json")))

        if not owner:
            raise _RESTError(400, "user_id is required to create a session.")
        store.save(
            owner,
            session_id,
            session_state=state,
            runs=runs,
            interaction_assessment=assessment,
        )
        log_info(f"rest: session {session_id} updated ({len(runs)} run(s))")
        return _session_response(
            session_id,
            {
                "session_id": session_id,
                "user_id": owner,
                "session_state": state,
                "runs": runs,
                "interaction_assessment": assessment,
            },
        )

    @staticmethod
    def _assessment(value: Optional[Any]) -> Optional[InteractionAssessment]:
        """Coerce the request payload to the canonical assessment type."""
        if value is None or isinstance(value, InteractionAssessment):
            return value
        try:
            return InteractionAssessment.model_validate(value)
        except ValidationError as exc:
            raise _RESTError(422, f"Invalid 'interaction_assessment': {exc.errors(include_url=False)}")

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------
    async def health(self) -> HealthResponse:
        """Liveness probe — no authentication."""
        return HealthResponse(name=self.name, version=_version())

    # ------------------------------------------------------------------
    # Router
    # ------------------------------------------------------------------
    def get_router(self) -> APIRouter:
        router = APIRouter(tags=["REST"])
        protected = [Depends(self._require_auth)]

        router.add_api_route(
            "/health",
            self.health,
            methods=["GET"],
            response_model=HealthResponse,
            summary="Liveness probe (public)",
        )
        router.add_api_route(
            "/runs",
            self.create_run,
            methods=["POST"],
            response_model=RunResponse,
            dependencies=protected,
            summary="Run one conversation turn",
            openapi_extra={"requestBody": _openapi_request_body()},
            description=(
                "Accepts either **application/json** (`message`, `session_id`, `user_id`, "
                "`files` with base64 `data`/`url`, `files_metadata`) or "
                "**multipart/form-data** (`message`, `session_id`, `user_id`, "
                "`files_metadata` as a JSON string, and file parts named `files`, "
                "`images`, `audio`, `videos` or `documents`). "
                "Requires `Authorization: Bearer <REST_API_KEY>`."
            ),
        )
        router.add_api_route(
            "/sessions/{session_id}/session",
            self.get_session,
            methods=["GET"],
            response_model=SessionResponse,
            dependencies=protected,
            summary="Read a persisted session",
        )
        router.add_api_route(
            "/sessions/{session_id}/session",
            self.update_session,
            methods=["POST"],
            response_model=SessionResponse,
            dependencies=protected,
            summary="Create or partially update a session",
        )
        return router
