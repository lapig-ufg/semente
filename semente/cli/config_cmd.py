"""``semente config`` — edit the app manifest (semente.yaml) from the terminal.

Enables/disables features, sets scalar/model keys, and manages the channel
list. The manifest is the single source of truth; everything is validated
before writing (``Manifest.save`` keeps a stable key order).

Enabling the tutorial goes one step further: it plants a working
``domain/tutorial.py`` example (the ``get_tutorial`` seam) and wires it into
the DomainSpec, so the app boots with a guided tutorial to edit instead of
an empty flag.
"""

from __future__ import annotations

import sys
from pathlib import Path

from semente.manifest import Manifest

KNOWN_FEATURES = ["tts", "summarization", "feedback_workflow", "pii_guardrail", "tutorial"]
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


def cmd_config_enable(feature: str, force: bool = False) -> None:
    manifest, path = _load_or_exit()
    if feature not in KNOWN_FEATURES:
        sys.exit(f"Unknown feature '{feature}' (available: {', '.join(KNOWN_FEATURES)})")
    manifest.features = {**manifest.features, feature: True}
    manifest.save(path)
    print(f"Feature '{feature}' enabled.")

    if feature == "tutorial":
        _enable_tutorial_scaffold(manifest, path, force)


def _enable_tutorial_scaffold(manifest: Manifest, path: Path, force: bool) -> None:
    """Plants the get_tutorial example so the flag has a working implementation."""
    from semente.cli.tutorial_scaffold import scaffold_tutorial

    report = scaffold_tutorial(manifest, path, force=force)
    for file in report.created:
        print(f"  created  {file}")
    for file in report.kept:
        print(f"  kept     {file} (use --force to overwrite)")
    if report.wired_file:
        state = "already wired" if report.already_wired else "wired"
        print(f"  {state}    {report.wired_file}")
    if report.manual_step:
        print(f"\nManual step: {report.manual_step}")
    if report.created or report.kept:
        print(
            "\nNext: edit domain/tutorial.py — every step is free text and the "
            "count is yours; run 'semente launch streamlit' to walk it."
        )


def cmd_config_disable(feature: str) -> None:
    manifest, path = _load_or_exit()
    if feature not in KNOWN_FEATURES:
        sys.exit(f"Unknown feature '{feature}' (available: {', '.join(KNOWN_FEATURES)})")
    manifest.features = {**manifest.features, feature: False}
    manifest.save(path)
    print(f"Feature '{feature}' disabled.")
    if feature == "tutorial":
        # The scaffolded example is user code now — the CLI never deletes it.
        print(
            "(domain/tutorial.py stays in place — re-enable the feature or "
            "remove the file yourself)"
        )


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