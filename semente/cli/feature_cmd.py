"""``semente feature`` — list, add, enable, and disable manifest features.

A feature is a framework capability gated by a key in the manifest's
``features`` block (absent keys default to the catalog's ``default_enabled``;
only ``terms-acceptance`` is off by default). ``add`` scaffolds an example
implementation in the app's domain when one exists (guardrails, terms) and
enables the feature; for framework-internal features ``add`` behaves like
``enable``.

Commands edit the manifest only, with one exception: enabling
``terms-acceptance`` for the first time (``add`` or ``--enable``) scaffolds
``domain/terms_example.md`` and points ``features.terms-acceptance.file`` at
it, so the gate never comes up without terms to show the user. An existing or
already-configured file is never overwritten.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console
from rich.table import Table

from semente.cli.common import load_manifest_or_exit, toggle_hint
from semente.manifest import FeedbackConfig, Manifest, TermsConfig

console = Console()


@dataclass(frozen=True)
class Feature:
    """One gateable framework capability (a manifest ``features`` key)."""

    name: str
    description: str
    scaffold: bool = False  # `feature add` writes an app-side example (domain/)
    default_enabled: bool = True  # absent key: on (True) or off (False)


FEATURES: dict[str, Feature] = {
    feature.name: feature
    for feature in (
        Feature("tts", "TTS tool on the welcoming agent (audio replies)"),
        Feature("summarization", "Rolling conversation summary (every 6 turns)"),
        Feature("interaction-assessment", "Satisfaction/persona loop, remediation cycles, DPO/SFT capture (enable + window_size)"),
        Feature("guardrails", "Pluggable input guardrails declared in DomainSpec", scaffold=True),
        Feature(
            "terms-acceptance",
            "Onboarding terms gate: first-message consent + DB record (enable + file/url)",
            scaffold=True,
            default_enabled=False,
        ),
    )
}

KNOWN_FEATURES = list(FEATURES)  # back-compat export (status_cmd imports this)

EXAMPLE_DIR = "domain"

TERMS_EXAMPLE_FILE = "terms_example.md"

TERMS_EXAMPLE_TEMPLATE = """\
# Terms of Use — {name}

> **Example document.** Scaffolded by `semente feature terms-acceptance --enable`.
> Replace it with your own terms before going to production.

## 1. Acceptance

By using {name} you agree to these terms. If you do not agree, please stop
using the service.

## 2. Service

{name} is provided as-is and for informational purposes. Features may change
or be discontinued at any time.

## 3. Data and privacy

Messages are processed only to provide the service. Do not share sensitive
personal data in the chat.

## 4. Contact

For questions about these terms, contact the app maintainers.
"""

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
    if name == "interaction-assessment":
        cfg = manifest.features.get("interaction-assessment")
        base = cfg if isinstance(cfg, FeedbackConfig) else FeedbackConfig()
        manifest.features = {
            **manifest.features,
            "interaction-assessment": base.model_copy(update={"enable": enabled}),
        }
        return
    if name == "terms-acceptance":
        cfg = manifest.features.get("terms-acceptance")
        base = cfg if isinstance(cfg, TermsConfig) else TermsConfig()
        manifest.features = {
            **manifest.features,
            "terms-acceptance": base.model_copy(update={"enable": enabled}),
        }
        return
    manifest.features = {**manifest.features, name: enabled}


def _feature_status(manifest: Manifest, name: str) -> str:
    """'enabled' / 'disabled' / 'default' (absent keys follow the catalog default)."""
    value = manifest.features.get(name)
    if value is None:
        return "default"
    if isinstance(value, (FeedbackConfig, TermsConfig)):
        return "enabled" if value.enable else "disabled"
    if isinstance(value, dict):
        return "enabled" if value.get("enable", True) else "disabled"
    return "enabled" if value else "disabled"


def _default_label(name: str) -> str:
    feature = FEATURES.get(name)
    return "default (on)" if feature is None or feature.default_enabled else "default (off)"


def _status_label(manifest: Manifest, name: str) -> str:
    status = _feature_status(manifest, name)
    if status == "default":
        return _default_label(name)
    return status


def _terms_config(manifest: Manifest) -> TermsConfig:
    """The manifest's terms config (normalized; absent means defaults)."""
    cfg = manifest.features.get("terms-acceptance")
    return cfg if isinstance(cfg, TermsConfig) else TermsConfig()


def _relative_to_manifest(target, manifest_path) -> str:
    """The portable path to write into the manifest (POSIX, manifest-relative)."""
    try:
        return target.resolve().relative_to(manifest_path.resolve().parent).as_posix()
    except ValueError:
        return target.as_posix()


def _ensure_terms_scaffold(manifest: Manifest, manifest_path) -> bool:
    """Scaffold the example terms and point the feature at it.

    Runs on the first enable. If ``file`` is already configured it is left
    alone (an app-owned document is never overwritten); a configured but
    missing path only warns — startup is where the hard error belongs.
    Returns True when it created/configured the example.
    """
    cfg = _terms_config(manifest)
    if cfg.file:
        path = Path(cfg.file)
        if not path.is_absolute():
            path = manifest_path.parent / path
        if not path.exists():
            print(f"Warning: features.terms-acceptance.file does not exist: {path}")
        return False

    example = manifest_path.parent / EXAMPLE_DIR / TERMS_EXAMPLE_FILE
    example.parent.mkdir(parents=True, exist_ok=True)

    if example.exists():
        print(f"Example already exists: {example} — configuring it.")
    else:
        example.write_text(
            TERMS_EXAMPLE_TEMPLATE.format(name=manifest.name), encoding="utf-8"
        )
        print(f"Scaffolded example: {example}")

    relative = _relative_to_manifest(example, manifest_path)
    manifest.features = {
        **manifest.features,
        "terms-acceptance": cfg.model_copy(update={"file": relative}),
    }
    print(f"Configured features.terms-acceptance.file: {relative}")
    return True


def cmd_feature_ls() -> None:
    manifest, path = load_manifest_or_exit()
    table = Table(show_header=True, box=None, title="Features", title_justify="left")
    table.add_column(style="bold cyan")
    table.add_column()
    table.add_column()
    for feature in FEATURES.values():
        status = _feature_status(manifest, feature.name)
        label = {
            "default": f"[yellow]{_default_label(feature.name)}[/yellow]",
            "enabled": "[green]enabled[/green]",
            "disabled": "[red]disabled[/red]",
        }[status]
        hint = "scaffoldable" if feature.scaffold else "framework-internal"
        table.add_row(feature.name, label, hint + " — " + feature.description)
    console.print(table)
    console.print(f"Manifest: {path} — toggle with 'semente feature <name> --enable/--disable'.")


def cmd_feature_actives() -> None:
    """One line per currently active feature (enabled or default-on)."""
    manifest, path = load_manifest_or_exit()
    active = []
    for feature in FEATURES.values():
        status = _feature_status(manifest, feature.name)
        if status == "enabled" or (status == "default" and feature.default_enabled):
            active.append(feature.name)
    console.print("[bold]Active features[/bold]: " + (", ".join(active) or "(none)"))
    console.print(f"Manifest: {path}")


def cmd_feature_toggle(name: str, enable: bool | None) -> None:
    """--enable/--disable toggles the manifest; without a flag shows the status."""
    feature_def = _validate(name)
    manifest, path = load_manifest_or_exit()

    if enable is None:
        print(f"Feature '{name}' is {_status_label(manifest, name)}.")
        print(toggle_hint("feature", name))
        return

    if enable and name == "terms-acceptance":
        _ensure_terms_scaffold(manifest, path)

    _feature_set(manifest, name, enable)
    manifest.save(path)
    verb = "enabled" if enable else "disabled"
    print(f"Feature '{name}' {verb}. (Manifest: {path})")


def cmd_feature_add(feature: str) -> None:
    """Enable the feature, scaffolding an example when one exists."""
    _validate(feature)
    manifest, path = load_manifest_or_exit()

    if feature == "guardrails":
        _scaffold_guardrails_example(path, manifest.name)
    elif feature == "terms-acceptance":
        _ensure_terms_scaffold(manifest, path)
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