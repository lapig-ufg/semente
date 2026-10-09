"""Multimodal input — semente media objects to provider-neutral wire parts.

``to_wire_parts`` resolves the framework's ``Image``/``Audio``/``File``
objects (bytes, filepath, or url — whatever the channel delivered) into the
provider-neutral part dicts the provider seam accepts (``kind``,
``mime_type``, ``data`` | ``url``). Unresolvable entries are dropped with a
warning — one bad photo must not sink the run.
"""

from __future__ import annotations

from pathlib import Path

_MIME_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".wav": "audio/wav",
    ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg",
    ".m4a": "audio/mp4",
    ".mp4": "video/mp4",
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".json": "application/json",
    ".geojson": "application/geo+json",
    ".zip": "application/zip",
}

_DEFAULT_MIME = {
    "image": "image/png",
    "audio": "audio/wav",
    "file": "application/octet-stream",
}


def _mime_for(kind: str, obj) -> str:
    if getattr(obj, "mime_type", None):
        return obj.mime_type
    path = getattr(obj, "filepath", None) or getattr(obj, "name", None) or ""
    return _MIME_BY_EXT.get(Path(str(path)).suffix.lower(), _DEFAULT_MIME[kind])


def _resolve(kind: str, obj) -> dict | None:
    """One media object -> one neutral part dict (or None if unresolvable)."""
    content = getattr(obj, "content", None)
    if content:
        return {"kind": kind, "mime_type": _mime_for(kind, obj), "data": content}

    url = getattr(obj, "url", None)
    if url:
        return {"kind": kind, "mime_type": _mime_for(kind, obj), "url": url}

    filepath = getattr(obj, "filepath", None)
    if filepath:
        try:
            data = Path(filepath).read_bytes()
        except OSError as e:
            from semente.logging import log_warning

            log_warning(f"dropping unresolvable {kind} at {filepath}: {e}")
            return None
        return {"kind": kind, "mime_type": _mime_for(kind, obj), "data": data}

    from semente.logging import log_warning

    log_warning(f"dropping {kind} with no content/url/filepath: {obj!r}")
    return None


def to_wire_parts(images=None, audio=None, files=None) -> list[dict]:
    """Semente media objects -> provider-neutral parts for the first round.

    Each part: ``{"kind": "image"|"audio"|"file", "mime_type": str,
    "data": bytes}`` or ``{..., "url": str}``. Kinds preserve order:
    images, then audio, then files.
    """
    parts: list[dict] = []
    for kind, items in (("image", images), ("audio", audio), ("file", files)):
        for obj in items or []:
            part = _resolve(kind, obj)
            if part is not None:
                parts.append(part)
    return parts