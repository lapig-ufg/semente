"""``semente init`` — scaffold a new Semente app.

Creates the minimal working app surface (modeled on the Pasto Legal reference
implementation): ``semente.yaml``, ``.env.example``, a ``domain/`` package with
the example tool and localized prompt files, ``main.py``, and ``.gitignore``.
Existing files are never overwritten without ``--force``.
"""

from __future__ import annotations

import sys
from pathlib import Path

from semente.cli.templates import (
    DOMAIN_INIT_TEMPLATE,
    GITIGNORE_TEMPLATE,
    MAIN_PY_TEMPLATE,
    SEMENTE_YAML_TEMPLATE,
    bundled_prompts_dir,
    default_model_id,
    env_example_content,
)


def _write_file(path: Path, content: str, force: bool, created: list[str], kept: list[str]) -> None:
    if path.exists() and not force:
        kept.append(str(path))
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    created.append(str(path))


def cmd_init(
    directory: str = ".",
    name: str | None = None,
    language: str = "en",
    provider: str = "google",
    force: bool = False,
    non_interactive: bool = False,
    stdin=sys.stdin,
) -> int:
    """Scaffold the app; returns the exit code."""
    if provider not in ("google", "ollama"):
        print(f"Invalid provider '{provider}' (available: google, ollama)")
        return 1

    project_dir = Path(directory)
    project_dir.mkdir(parents=True, exist_ok=True)

    app_name = name or project_dir.resolve().name
    if not non_interactive and stdin is not None and stdin.isatty():
        answer = input(f"App name [{app_name}]: ").strip()
        if answer:
            app_name = answer

    manifest_path = project_dir / "semente.yaml"
    if manifest_path.exists() and not force:
        print(f"'{manifest_path}' already exists — use 'semente config' to edit it, or --force to overwrite.")
        return 1

    created: list[str] = []
    kept: list[str] = []

    _write_file(
        manifest_path,
        SEMENTE_YAML_TEMPLATE.format(
            name=app_name, language=language, provider=provider, model_id=default_model_id(provider)
        ),
        force,
        created,
        kept,
    )
    _write_file(project_dir / ".env.example", env_example_content(app_name, provider), force, created, kept)
    _write_file(project_dir / "main.py", MAIN_PY_TEMPLATE.format(name=app_name), force, created, kept)
    _write_file(project_dir / ".gitignore", GITIGNORE_TEMPLATE, force, created, kept)
    _write_file(project_dir / "domain" / "__init__.py", DOMAIN_INIT_TEMPLATE.format(name=app_name), force, created, kept)

    defaults = bundled_prompts_dir()
    for prompts_file in ("agents.yml", "tools.yml", "hooks.yml"):
        source = defaults / prompts_file
        _write_file(
            project_dir / "domain" / "prompts" / prompts_file,
            source.read_text(encoding="utf-8"),
            force,
            created,
            kept,
        )

    print(f"Initialized Semente app '{app_name}' in {project_dir.resolve()}\n")
    for path in created:
        print(f"  created  {path}")
    for path in kept:
        print(f"  kept     {path} (use --force to overwrite)")
    print(
        "\nNext steps:\n"
        f"  1. cp {project_dir / '.env.example'} {project_dir / '.env'}  "
        "(or skip: the first-run wizard fills the model values)\n"
        f"  2. semente status\n"
        f"  3. semente launch streamlit\n"
        f"  4. edit domain/__init__.py with your tools — see docs/guide/domain.md"
    )
    return 0