"""App manifest — parsed ``semente.yaml``.

Kept in its own module (not in build.py) to avoid a circular import: the
workflow builder needs it, and build.py imports the workflow builder.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from pydantic import BaseModel, Field
from semente.logging import log_warning

class FeedbackConfig(BaseModel):
    enable: bool = Field(default=True)
    window_size: int = Field(default=5, ge=1)
    
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
        features_data = data.get("features", {})
        # Legacy alias: the old hard-wired PII stage was features.pii_guardrail
        # and became the pluggable features.guardrails. Normalized here so the
        # rest of the code (and to_dict) sees a single key.
        if "pii_guardrail" in features_data:
            log_warning("features.pii_guardrail is deprecated; rename it to features.guardrails")
            if "guardrails" not in features_data:
                features_data["guardrails"] = features_data.pop("pii_guardrail")
            else:
                features_data = {k: v for k, v in features_data.items() if k != "pii_guardrail"}
        # Legacy keys (normalized here, like the pii_guardrail alias above):
        # `feedback_workflow` (the per-turn loop gate), `feedback` (its DPO/SFT
        # capture, enable + window_size), and the branch-intermediate
        # `interaction_assessment` snake_case spelling — `interaction-assessment`
        # (kebab-case, the feature-naming convention) subsumes all of them.
        # An explicit kebab-case key wins entirely; with only legacy keys, the
        # `feedback` dict decides the structure/window and any `false` gate
        # disables the feature.
        ia_val = features_data.pop("interaction-assessment", None)
        if ia_val is None:
            ia_val = features_data.pop("interaction_assessment", None)
            if ia_val is not None:
                log_warning("features.interaction_assessment is deprecated; rename it to features.interaction-assessment")
        else:
            features_data.pop("interaction_assessment", None)
        feedback_val = features_data.pop("feedback", None)
        if feedback_val is not None:
            log_warning("features.feedback is deprecated; rename it to features.interaction-assessment")
        legacy_loop = features_data.pop("feedback_workflow", None)
        if legacy_loop is not None:
            log_warning("features.feedback_workflow is deprecated; rename it to features.interaction-assessment")

        sources = [ia_val] if ia_val is not None else [v for v in (feedback_val, legacy_loop) if v is not None]
        gates: list[bool] = []
        window_size: int | None = None
        for value in sources:
            if isinstance(value, dict):
                gates.append(bool(value.get("enable", True)))
                if value.get("window_size") is not None:
                    window_size = value["window_size"]
            elif isinstance(value, FeedbackConfig):
                gates.append(value.enable)
                window_size = value.window_size
            else:  # bool
                gates.append(bool(value))
        features_data["interaction-assessment"] = FeedbackConfig(
            enable=all(gates),
            window_size=window_size if window_size is not None else 5,
        )
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
            if "interaction-assessment" in data["features"] and isinstance(
                data["features"]["interaction-assessment"], FeedbackConfig
            ):
                data["features"]["interaction-assessment"] = data["features"]["interaction-assessment"].model_dump()
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
