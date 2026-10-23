"""``semente provider`` — model providers, model ids, fallback, and API keys.

Model config has two layers. The base is the environment (``.env``:
``PRIMARY_MODEL_*``, ``FALLBACK_*`` and the provider keys); the manifest's
``models:`` block overrides it. This command:

- writes the manifest override for provider/model choices
  (``primary``/``fallback``);
- writes API keys (secrets) into ``.env`` via the wizard helpers — never
  into ``semente.yaml``;
- shows the effective configuration and what is missing (``ls``).
"""

from __future__ import annotations

import sys
from getpass import getpass
from pathlib import Path

from rich.console import Console
from rich.table import Table

from semente.cli.common import load_manifest_or_exit
from semente.configs.wizard import (
    _PROVIDER_KEYS,
    effective_env,
    get_missing,
    save_to_env_file,
)

console = Console()

KNOWN_PROVIDERS = list(_PROVIDER_KEYS)


def _validate(provider: str) -> None:
    if provider not in KNOWN_PROVIDERS:
        sys.exit(f"Unknown provider '{provider}' (available: {', '.join(KNOWN_PROVIDERS)})")


def cmd_provider_ls() -> None:
    """Effective primary/fallback configuration and missing keys."""
    manifest, path = load_manifest_or_exit()
    env = effective_env()
    missing = set(get_missing(env))

    table = Table(show_header=True, box=None, title="Providers", title_justify="left")
    table.add_column(style="bold cyan")
    table.add_column()
    table.add_column()

    def _role_rows(role: str, manifest_cfg: dict | None) -> None:
        manifest_cfg = manifest_cfg or {}
        provider = manifest_cfg.get("provider") or env.get(f"{role.upper()}_MODEL_PROVIDER") or ""
        model_id = manifest_cfg.get("id") or env.get(f"{role.upper()}_MODEL_ID") or ""
        source = "manifest" if manifest_cfg.get("provider") or manifest_cfg.get("id") else ".env"
        table.add_row(f"{role} — provider", provider or "-", source)
        table.add_row(f"{role} — model", model_id or "-", source)
        keys = _PROVIDER_KEYS.get(provider, []) if provider else []
        for key in keys:
            if "API_KEY" in key:
                state = "[green]set[/green]" if key not in missing else "[red]missing[/red]"
                table.add_row(f"{role} — {key}", state, ".env")

    _role_rows("primary", manifest.models.get("primary"))
    if manifest.models.get("fallback") or env.get("FALLBACK_MODEL_PROVIDER"):
        _role_rows("fallback", manifest.models.get("fallback"))
    else:
        table.add_row("fallback", "[yellow]none[/yellow]", "—")

    console.print(table)
    hint = (
        "'semente provider primary <provider> --model <id>', "
        "'semente provider fallback <provider>' / '--disable', "
        "'semente provider key <provider>'."
    )
    console.print(f"Manifest: {path} — configure with {hint}")


def cmd_provider_primary(provider: str, model: str | None = None) -> None:
    """Set the primary provider (and model id) in the manifest."""
    _validate(provider)
    manifest, path = load_manifest_or_exit()
    models = dict(manifest.models)
    primary = {**(models.get("primary") or {}), "provider": provider}
    if model:
        primary["id"] = model
    models["primary"] = primary
    manifest.models = models
    manifest.save(path)
    shown = f"{provider} / {model}" if model else provider
    print(f"Primary model = {shown}. (Manifest: {path})")
    if not model:
        print("Model id untouched — set it with 'semente provider primary "
              f"{provider} --model <id>' or leave it to .env/wizard defaults.")


def cmd_provider_fallback(provider: str | None, model: str | None = None, disable: bool = False) -> None:
    """Set or remove the fallback model (the second, single retry on error)."""
    manifest, path = load_manifest_or_exit()
    models = dict(manifest.models)

    if disable:
        if not models.pop("fallback", None):
            print("No fallback configured in the manifest already.")
            return
        manifest.models = models
        manifest.save(path)
        print(f"Fallback removed from the manifest. (Manifest: {path})")
        return

    if not provider:
        fb = manifest.models.get("fallback") or {}
        env = effective_env()
        env_provider = env.get("FALLBACK_MODEL_PROVIDER") or ""
        if manifest.models.get("fallback") or env_provider:
            source = "manifest" if manifest.models.get("fallback") else ".env"
            shown_fb = fb.get("provider") or env_provider
            shown_model = fb.get("id") or env.get("FALLBACK_MODEL_ID") or ""
            detail = f"{shown_fb} / {shown_model}" if shown_model else shown_fb
            print(f"Fallback configured: {detail} (from {source}).")
            print("Set a different fallback: 'semente provider fallback <provider> [--model <id>]' · "
                  "remove it: 'semente provider fallback --disable'.")
        else:
            print("No fallback model configured — the primary has no backup.")
            print("Set one: 'semente provider fallback <provider> [--model <id>]' · "
                  "remove it later with 'semente provider fallback --disable'.")
        return

    _validate(provider)
    if provider == (models.get("primary") or {}).get("provider"):
        print("Note: fallback uses the same provider as the primary — set a different "
              "model id so a failure makes sense (e.g. another model).")
    fallback = {**(models.get("fallback") or {}), "provider": provider}
    if model:
        fallback["id"] = model
    models["fallback"] = fallback
    manifest.models = models
    manifest.save(path)
    shown = f"{provider} / {model}" if model else provider
    print(f"Fallback model = {shown}. One retry with it covers any primary failure. (Manifest: {path})")
    if not model:
        print("Model id untouched — set it with 'semente provider fallback "
              f"{provider} --model <id>' or leave it to .env defaults.")


def cmd_provider_key(provider: str, input_fn=None, getpass_fn=None) -> None:
    """Prompt for the provider's secret keys and write them into .env."""
    _validate(provider)
    input_fn = input_fn or input
    getpass_fn = getpass_fn or getpass
    # Resolved at call time: the .env lives in the cwd (like load_dotenv), and
    # this keeps tests — which chdir after import — away from the repo's .env.
    env_path = Path.cwd() / ".env"
    print(f"Keys for provider '{provider}' are stored in {env_path} (never in semente.yaml).")
    env = effective_env()
    answers: list[dict[str, str]] = []
    for key in _PROVIDER_KEYS[provider]:
        current = (env.get(key) or "").strip()
        value = ""
        if key.endswith("_API_KEY"):
            value = getpass_fn(f"{key} (hidden; current {'set' if current else 'unset'}): ").strip()
            if not value:
                print(f"{key} kept ({'set — unchanged' if current else 'unset — empty answer'}).")
                continue
        else:
            value = input_fn(f"{key} [current: {current or 'unset'}]: ").strip() or current
            if not value:
                print(f"{key} kept unset.")
                continue
        answers.append({"key": key, "value": value})
    if not answers:
        print("Nothing to write.")
        return
    save_to_env_file(env_path, answers)
    for answer in answers:
        shown = "•" * 8 if answer["key"].endswith("_API_KEY") else answer["value"]
        print(f"  {answer['key']}={shown} written to {env_path}")