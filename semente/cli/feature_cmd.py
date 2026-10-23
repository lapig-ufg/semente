"""``semente feature`` — list, add, enable, and disable manifest features.

A feature is a framework capability gated by a key in the manifest's
``features`` block (absent keys default to enabled). ``add`` scaffolds an
example implementation in the app's domain when one exists (guardrails) and
enables the feature; for framework-internal features ``add`` behaves like
``enable``. Both commands edit the manifest only — they never touch app code.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

from rich.console import Console
from rich.table import Table

from semente.cli.config_cmd import _load_or_exit
from semente.manifest import FeedbackConfig, Manifest

console = Console()


@dataclass(frozen=True)
class Feature:
    """One gateable framework capability (a manifest ``features`` key)."""

    name: str
    description: str
    scaffold: bool = False  # `feature add` writes an app-side example (domain/)


FEATURES: dict[str, Feature] = {
    feature.name: feature
    for feature in (
        Feature("tts", "TTS tool on the welcoming agent (audio replies)"),
        Feature("feedback_workflow", "Satisfaction/persona loop, remediation cycles"),
        Feature("summarization", "Rolling conversation summary (every 6 turns)"),
        Feature("guardrails", "Pluggable input guardrails declared in DomainSpec", scaffold=True),
        Feature("feedback", "DPO/SFT trajectory capture (enable + window_size)"),
    )
}

KNOWN_FEATURES = list(FEATURES)  # back-compat export (status_cmd imports this)

EXAMPLE_DIR = "domain"

GUARDRAILS_EXAMPLE_TEMPLATE = '''\
"""Example guardrails — scaffolded by `semente feature add guardrails`.

Semente runs the DomainSpec's guardrails in list order over every user
input: each guard may redact sensitive spans or block the turn with a
user-facing reply (the agent never runs on a blocked turn). Keep this
module engine-free — see docs/guide/guardrails.md.

Plug into your domain::

    from domain.guardrails_example import GUARDRAILS

    domain_spec = DomainSpec(name="{name}", tools=[...], guardrails=GUARDRAILS)
"""

from __future__ import annotations

from semente.guardrails import CardGuardrail, EmailGuardrail

# Ready-to-use, universally-safe guards. Mix in your own by subclassing
# RegexGuardrail (semente.guardrails) — country-specific detectors belong
# to the domain, not the framework.
GUARDRAILS = [
    EmailGuardrail(),
    CardGuardrail(),
]
'''


def _validate(name: str) -> Feature:
    feature = FEATURES.get(name)
    if feature is None:
        sys.exit(f"Unknown feature '{name}' (available: {', '.join(KNOWN_FEATURES)})")
    return feature


def _feature_set(manifest: Manifest, name: str, enabled: bool) -> None:
    """Enable/disable ``features.<name>``, keeping any nested config."""
    if name == "feedback":
        cfg = manifest.features.get("feedback")
        base = cfg if isinstance(cfg, FeedbackConfig) else FeedbackConfig()
        manifest.features = {
            **manifest.features,
            "feedback": base.model_copy(update={"enable": enabled}),
        }
        return
    manifest.features = {**manifest.features, name: enabled}


def _feature_status(manifest: Manifest, name: str) -> str:
    """'enabled' / 'disabled' / 'default' (absent keys default to enabled)."""
    value = manifest.features.get(name)
    if value is None:
        return "default"
    if isinstance(value, FeedbackConfig):
        return "enabled" if value.enable else "disabled"
    if isinstance(value, dict):
        return "enabled" if value.get("enable", True) else "disabled"
    return "enabled" if value else "disabled"


def cmd_feature_ls() -> None:
    manifest, path = _load_or_exit()
    table = Table(show_header=True, box=None, title="Features", title_justify="left")
    table.add_column(style="bold cyan")
    table.add_column()
    table.add_column()
    for feature in FEATURES.values():
        status = _feature_status(manifest, feature.name)
        label = {"default": "[yellow]default (on)[/yellow]",
                 "enabled": "[green]enabled[/green]",
                 "disabled": "[red]disabled[/red]"}[status]
        hint = "scaffoldable" if feature.scaffold else "framework-internal"
        table.add_row(feature.name, label, hint + " — " + feature.description)
    console.print(table)
    console.print(f"Manifest: {path} — toggle with 'semente feature enable/disable <name>'.")


def cmd_feature_enable(feature: str) -> None:
    _validate(feature)
    manifest, path = _load_or_exit()
    _feature_set(manifest, feature, True)
    manifest.save(path)
    print(f"Feature '{feature}' enabled. (Manifest: {path})")


def cmd_feature_disable(feature: str) -> None:
    _validate(feature)
    manifest, path = _load_or_exit()
    _feature_set(manifest, feature, False)
    manifest.save(path)
    print(f"Feature '{feature}' disabled. Existing code is left in place — only the manifest toggles it. (Manifest: {path})")


def cmd_feature_add(feature: str) -> None:
    """Enable the feature, scaffolding an example when one exists."""
    feature_def = _validate(feature)
    manifest, path = _load_or_exit()

    if feature_def.scaffold:
        _scaffold_guardrails_example(path, manifest.name)
    else:
        print(f"'{feature}' is framework-internal — no app-side example to scaffold; enabling it only.")

    _feature_set(manifest, feature, True)
    manifest.save(path)
    print(f"Feature '{feature}' enabled. (Manifest: {path})")


def _scaffold_guardrails_example(manifest_path, app_name: str) -> None:
    example = manifest_path.parent / EXAMPLE_DIR / "guardrails_example.py"
    if example.exists():
        print(f"Example already exists: {example} — leaving it untouched.")
        return
    example.parent.mkdir(parents=True, exist_ok=True)
    example.write_text(GUARDRAILS_EXAMPLE_TEMPLATE.format(name=app_name), encoding="utf-8")
    print(f"Scaffolded example: {example}")