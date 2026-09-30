"""``semente config`` — edit the app manifest (semente.yaml) from the terminal.

Enables/disables features, sets scalar/model keys, and manages the channel
list. The manifest is the single source of truth; everything is validated
before writing (``Manifest.save`` keeps a stable key order).
"""

from __future__ import annotations

import sys
from pathlib import Path

from semente.manifest import Manifest

KNOWN_FEATURES = ["tts", "summarization", "feedback_workflow", "pii_guardrail"]
KNOWN_CHANNELS = ["streamlit", "whatsapp"]
KNOWN_ENGINES = ["agno", "adk", "bare"]
KNOWN_PROVIDERS = ["google", "ollama"]

_SIMPLE_KEYS = ["name", "language", "domain_module", "prompts_dir"]
_MODEL_KEYS = {
    "models.primary.provider": KNOWN_PROVIDERS,
    "models.primary.id": None,
    "models.fallback.provider": KNOWN_PROVIDERS,
    "models.fallback.id": None,
}


def manifest_path_or_exit() -> Path:
    """SEMENTE_MANIFEST > ./semente.yaml, else exit with an actionable hint."""
    import os

    path = Path(os.getenv("SEMENTE_MANIFEST") or "semente.yaml")
    if not path.exists():
        sys.exit(
            f"No manifest found ('{path}'). Run 'semente init' to create one, "
            "or set SEMENTE_MANIFEST."
        )
    return path


def _load_or_exit() -> tuple[Manifest, Path]:
    path = manifest_path_or_exit()
    return Manifest.load(path), path


def _set_nested(manifest: Manifest, key: str, value: str) -> str:
    """Set a dotted key; returns a human description of what was set."""
    if key == "engine":
        if value not in KNOWN_ENGINES:
            sys.exit(f"Invalid engine '{value}' (available: {', '.join(KNOWN_ENGINES)})")
        manifest.engine = value
        return f"engine = {value!r}"

    if key in _SIMPLE_KEYS:
        setattr(manifest, key, value)
        return f"{key} = {value!r}"

    if key in _MODEL_KEYS:
        allowed = _MODEL_KEYS[key]
        if allowed is not None and value not in allowed:
            sys.exit(f"Invalid value '{value}' for {key} (available: {', '.join(allowed)})")
        _, role, field = key.split(".")
        models = dict(manifest.models)
        models[role] = {**models.get(role, {}), field: value}
        manifest.models = models
        return f"{key} = {value!r}"

    valid = ", ".join(_SIMPLE_KEYS + list(_MODEL_KEYS))
    sys.exit(f"Unknown key '{key}' (valid: {valid})")


def cmd_config_enable(feature: str) -> None:
    manifest, path = _load_or_exit()
    if feature not in KNOWN_FEATURES:
        sys.exit(f"Unknown feature '{feature}' (available: {', '.join(KNOWN_FEATURES)})")
    manifest.features = {**manifest.features, feature: True}
    manifest.save(path)
    print(f"Feature '{feature}' enabled.")


def cmd_config_disable(feature: str) -> None:
    manifest, path = _load_or_exit()
    if feature not in KNOWN_FEATURES:
        sys.exit(f"Unknown feature '{feature}' (available: {', '.join(KNOWN_FEATURES)})")
    manifest.features = {**manifest.features, feature: False}
    manifest.save(path)
    print(f"Feature '{feature}' disabled.")


def cmd_config_set(key: str, value: str) -> None:
    manifest, path = _load_or_exit()
    description = _set_nested(manifest, key, value)
    manifest.save(path)
    print(description)


def cmd_config_channel_add(channel: str) -> None:
    manifest, path = _load_or_exit()
    if channel not in KNOWN_CHANNELS:
        sys.exit(f"Unknown channel '{channel}' (available: {', '.join(KNOWN_CHANNELS)})")
    if channel in manifest.channels:
        print(f"Channel '{channel}' already enabled.")
        return
    manifest.channels = [*manifest.channels, channel]
    manifest.save(path)
    print(f"Channel '{channel}' enabled. Channels: {', '.join(manifest.channels)}")


def cmd_config_channel_remove(channel: str) -> None:
    manifest, path = _load_or_exit()
    if channel not in manifest.channels:
        print(f"Channel '{channel}' is not enabled. Channels: {', '.join(manifest.channels)}")
        return
    manifest.channels = [c for c in manifest.channels if c != channel]
    manifest.save(path)
    print(f"Channel '{channel}' disabled. Channels: {', '.join(manifest.channels) or '(none)'}")