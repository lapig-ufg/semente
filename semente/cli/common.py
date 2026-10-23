"""Shared manifest-editing helpers for the CLI commands.

Every manifest-editing command (feature, channel, provider) resolves the
manifest the same way: ``SEMENTE_MANIFEST`` env var > ``./semente.yaml``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from semente.manifest import Manifest


def manifest_path_or_exit() -> Path:
    """SEMENTE_MANIFEST > ./semente.yaml, else exit with an actionable hint."""
    path = Path(os.getenv("SEMENTE_MANIFEST") or "semente.yaml")
    if not path.exists():
        sys.exit(
            f"No manifest found ('{path}'). Run 'semente init' to create one, "
            "or set SEMENTE_MANIFEST."
        )
    return path


def load_manifest_or_exit() -> tuple[Manifest, Path]:
    """Load the app manifest or exit with the init hint."""
    path = manifest_path_or_exit()
    return Manifest.load(path), path


def toggle_hint(command: str, name: str) -> str:
    """The always-present hint naming both toggle options for an item."""
    return (
        f"Enable: 'semente {command} {name} --enable' · "
        f"Disable: 'semente {command} {name} --disable'"
    )