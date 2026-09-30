"""``semente status`` — the app at a glance: manifest, env health, doctor checks.

Doctor checks are static (file existence + AST parsing) — the domain module is
never imported, avoiding side effects like GEE authentication or network calls.
"""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from semente.cli.config_cmd import KNOWN_FEATURES
from semente.configs.wizard import effective_env, get_missing, required_keys
from semente.manifest import Manifest


def _mask(value: str) -> str:
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:3]}...{value[-3:]}"


def _domain_spec_check(module: str) -> tuple[str, str]:
    """Static check: does <module>/__init__.py (or <module>.py) expose domain_spec?"""
    package_init = Path(module) / "__init__.py"
    module_file = Path(f"{module}.py")
    source_file = package_init if package_init.exists() else module_file
    if not source_file.exists():
        return "fail", f"'{module}' module not found"
    try:
        tree = ast.parse(source_file.read_text(encoding="utf-8"))
    except SyntaxError:
        return "fail", f"'{source_file}' has a syntax error"
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "domain_spec":
                    return "ok", f"'{module}' exposes domain_spec"
    return "warn", f"'{source_file}' does not expose 'domain_spec'"


def _prompts_check(prompts_dir: str | None) -> tuple[str, str]:
    """Check the localized prompts files (fall back to bundled defaults when absent)."""
    if not prompts_dir:
        return "ok", "no prompts_dir — bundled English defaults are used"
    directory = Path(prompts_dir)
    if not directory.is_dir():
        return "warn", f"prompts_dir '{prompts_dir}' does not exist — bundled defaults are used"
    missing = [f for f in ("agents.yml", "tools.yml", "hooks.yml") if not (directory / f).exists()]
    if missing:
        return "warn", f"prompts_dir misses {', '.join(missing)} — those fall back to bundled defaults"
    return "ok", f"prompts_dir '{prompts_dir}' complete (agents/tools/hooks.yml)"


def cmd_status() -> int:
    """Print the app status; returns the exit code (0 even without a manifest)."""
    console = Console()
    manifest_path = os.getenv("SEMENTE_MANIFEST") or "semente.yaml"
    if not Path(manifest_path).exists():
        console.print(f"[yellow]No manifest found ('{manifest_path}').[/yellow]")
        console.print("Run [bold]semente init[/bold] to create an app, or set SEMENTE_MANIFEST.")
        return 0

    manifest = Manifest.load(manifest_path)
    env = effective_env()
    missing_env = get_missing(env)

    # --- App table -----------------------------------------------------------
    app = Table(show_header=False, box=None, title="App", title_justify="left")
    app.add_column(style="bold cyan")
    app.add_column()
    app.add_row("name", manifest.name)
    app.add_row("language", manifest.language)
    app.add_row("engine", manifest.engine or "agno (default)")
    app.add_row("domain_module", manifest.domain_module)
    app.add_row("prompts_dir", manifest.prompts_dir or "(bundled defaults)")
    app.add_row("manifest", str(manifest_path))
    app.add_row("APP_ENV", env.get("APP_ENV") or "development")
    console.print(app)

    # --- Channels & Features -------------------------------------------------
    channels = Table(show_header=False, box=None, title="Channels", title_justify="left")
    channels.add_column(style="bold cyan")
    channels.add_column()
    for channel in manifest.channels:
        channels.add_row(channel, "[green]enabled[/green]")
    console.print(channels)

    features = Table(show_header=False, box=None, title="Features", title_justify="left")
    features.add_column(style="bold cyan")
    features.add_column()
    for feature in KNOWN_FEATURES:
        value = manifest.features.get(feature, True)  # default: enabled
        features.add_row(feature, "[green]enabled[/green]" if value else "[red]disabled[/red]")
    console.print(features)

    # --- Models --------------------------------------------------------------
    models = Table(show_header=False, box=None, title="Models", title_justify="left")
    models.add_column(style="bold cyan")
    models.add_column()
    primary = (manifest.models or {}).get("primary") or {}
    models.add_row("primary", f"{primary.get('provider', 'google (env)')} / {primary.get('id', '(from env)')}")
    fallback = (manifest.models or {}).get("fallback")
    if fallback:
        models.add_row("fallback", f"{fallback.get('provider', '?')} / {fallback.get('id', '?')}")
    else:
        models.add_row("fallback", "(none)")
    console.print(models)

    # --- Environment health ---------------------------------------------------
    environment = Table(show_header=False, box=None, title="Environment", title_justify="left")
    environment.add_column(style="bold cyan")
    environment.add_column()
    for key in required_keys(env):
        value = (env.get(key) or "").strip()
        if value:
            shown = _mask(value) if "KEY" in key else value
            environment.add_row(key, f"[green]{shown}[/green]")
        else:
            environment.add_row(key, "[red]missing[/red]")
    if missing_env:
        environment.add_row(
            "hint", "run [bold]semente launch streamlit[/bold] — the wizard asks for the missing values"
        )
    console.print(environment)

    # --- Doctor ---------------------------------------------------------------
    doctor = Table(show_header=False, box=None, title="Doctor", title_justify="left")
    doctor.add_column(style="bold cyan")
    doctor.add_column()
    icon = {"ok": "[green]OK[/green]", "warn": "[yellow]WARN[/yellow]", "fail": "[red]FAIL[/red]"}
    status, detail = _domain_spec_check(manifest.domain_module)
    doctor.add_row("domain", f"{icon[status]} {detail}")
    status, detail = _prompts_check(manifest.prompts_dir)
    doctor.add_row("prompts", f"{icon[status]} {detail}")
    console.print(doctor)

    return 0