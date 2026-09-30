"""App manifest — parsed ``semente.yaml``.

Kept in its own module (not in build.py) to avoid a circular import: the
workflow builder needs it, and build.py imports the workflow builder.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class Manifest:
    """Parsed ``semente.yaml`` — app-level configuration."""

    name: str
    language: str = "en"
    domain_module: str = "domain"
    prompts_dir: str | None = None
    engine: str | None = None  # None -> SEMENTE_ENGINE env var -> "agno"
    channels: list[str] = field(default_factory=lambda: ["streamlit"])
    features: dict[str, bool] = field(default_factory=dict)
    models: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path) -> "Manifest":
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return cls(
            name=data.get("name", "semente-app"),
            language=data.get("language", "en"),
            domain_module=data.get("domain_module", "domain"),
            prompts_dir=data.get("prompts_dir"),
            engine=data.get("engine"),
            channels=data.get("channels", ["streamlit"]),
            features=data.get("features", {}),
            models=data.get("models", {}),
        )

    def to_dict(self) -> dict[str, Any]:
        """The manifest as a YAML-ready dict (stable key order, no None fields)."""
        data: dict[str, Any] = {
            "name": self.name,
            "language": self.language,
            "domain_module": self.domain_module,
        }
        if self.prompts_dir:
            data["prompts_dir"] = self.prompts_dir
        if self.engine:
            data["engine"] = self.engine
        data["channels"] = list(self.channels)
        if self.features:
            data["features"] = dict(self.features)
        if self.models:
            data["models"] = {k: dict(v) for k, v in self.models.items()}
        return data

    def save(self, path: str | Path) -> None:
        """Write the manifest back to ``semente.yaml`` (stable key order).

        Note: YAML comments are not preserved — manifests are expected to be
        comment-free (the CLI is the editor).
        """
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(self.to_dict(), f, sort_keys=False, allow_unicode=True)
