"""semente init: scaffolding, overwrite behavior, non-interactive defaults."""

import sys
from pathlib import Path

from semente.cli.init_cmd import cmd_init


class NoTTY:
    def isatty(self):
        return False


def _scaffold(tmp_path, **kwargs):
    """Run init with all defaults (non-interactive)."""
    defaults = dict(
        directory=str(tmp_path),
        non_interactive=True,
        stdin=NoTTY(),
    )
    defaults.update(kwargs)
    return cmd_init(**defaults)


def test_init_creates_full_scaffold(tmp_path):
    assert _scaffold(tmp_path) == 0

    expected = [
        "semente.yaml",
        ".env.example",
        "main.py",
        ".gitignore",
        "domain/__init__.py",
        "domain/prompts/agents.yml",
        "domain/prompts/tools.yml",
        "domain/prompts/hooks.yml",
    ]
    for rel in expected:
        assert (tmp_path / rel).exists(), f"missing: {rel}"


def test_init_manifest_content(tmp_path):
    """The scaffolded manifest parses and carries the chosen values."""
    from semente.manifest import Manifest

    _scaffold(tmp_path, name="my-farm", language="pt-BR", provider="ollama")
    manifest = Manifest.load(tmp_path / "semente.yaml")

    assert manifest.name == "my-farm"
    assert manifest.language == "pt-BR"
    assert manifest.domain_module == "domain"
    assert manifest.channels == ["streamlit"]
    assert manifest.features["tts"] is True
    assert manifest.features["pii_guardrail"] is True
    assert manifest.models["primary"]["provider"] == "ollama"
    assert manifest.models["primary"]["id"]  # the ollama default id


def test_init_env_example_matches_provider(tmp_path):
    _scaffold(tmp_path, provider="ollama")
    content = (tmp_path / ".env.example").read_text(encoding="utf-8")
    assert 'PRIMARY_MODEL_PROVIDER="ollama"' in content
    assert "OLLAMA_HOST" in content
    assert 'PRIMARY_MODEL_PROVIDER="google"' not in content


def test_init_domain_spec_is_importable(tmp_path):
    """The scaffolded domain module exposes a valid domain_spec."""
    import importlib

    _scaffold(tmp_path, name="Test App")
    sys.path.insert(0, str(tmp_path))
    try:
        domain = importlib.import_module("domain")
        spec = domain.domain_spec
        assert spec.name == "Test App"
        assert len(spec.tools) == 1  # the example echo tool
    finally:
        if str(tmp_path) in sys.path:
            sys.path.remove(str(tmp_path))
        sys.modules.pop("domain", None)


def test_init_refuses_existing_manifest(tmp_path, capsys):
    """A second init without --force fails and points to config."""
    assert _scaffold(tmp_path) == 0
    code = _scaffold(tmp_path)
    assert code == 1
    assert "semente config" in capsys.readouterr().out


def test_init_keeps_existing_files(tmp_path):
    """Without --force, existing files are kept; the rest is scaffolded."""
    config = tmp_path / "domain" / "prompts" / "agents.yml"
    config.parent.mkdir(parents=True)
    config.write_text("# my custom prompts\n")

    code = _scaffold(tmp_path)

    assert code == 0
    assert config.read_text(encoding="utf-8") == "# my custom prompts\n"
    assert (tmp_path / "semente.yaml").exists()
    assert (tmp_path / "domain" / "prompts" / "tools.yml").exists()


def test_init_force_overwrites(tmp_path):
    config = tmp_path / "domain" / "prompts" / "agents.yml"
    config.parent.mkdir(parents=True)
    config.write_text("# my custom prompts\n")

    _scaffold(tmp_path, force=True)

    assert config.read_text(encoding="utf-8") != "# my custom prompts\n"


def test_init_invalid_provider(tmp_path):
    assert _scaffold(tmp_path, provider="openai") == 1


def test_init_creates_nested_directory(tmp_path):
    target = tmp_path / "apps" / "new-farm"
    assert _scaffold(target, non_interactive=True, stdin=NoTTY()) == 0
    assert (target / "semente.yaml").exists()


def test_init_default_name_from_directory(tmp_path):
    from semente.manifest import Manifest

    target = tmp_path / "named-farm"
    _scaffold(target, non_interactive=True, stdin=NoTTY())
    assert Manifest.load(target / "semente.yaml").name == "named-farm"


# ---------------------------------------------------------------------
# The guided-tutorial example (--tutorial / interactive prompt)
# ---------------------------------------------------------------------


class _TTY:
    def isatty(self):
        return True


def _answers(*values):
    """Canned `input` answers, in order."""
    queue = iter(values)
    return lambda *a, **k: next(queue)


def test_init_tutorial_flag_scaffolds_and_wires(tmp_path):
    import importlib

    from semente.manifest import Manifest

    _scaffold(tmp_path, name="My Farm", tutorial=True)

    manifest = Manifest.load(tmp_path / "semente.yaml")
    assert manifest.features["tutorial"] is True
    assert (tmp_path / "domain" / "tutorial.py").exists()
    init_py = (tmp_path / "domain" / "__init__.py").read_text(encoding="utf-8")
    assert "from .tutorial import get_tutorial" in init_py
    assert "get_tutorial=get_tutorial" in init_py

    # The wired spec is real: importing the domain exposes get_tutorial.
    sys.modules.pop("domain", None)
    sys.path.insert(0, str(tmp_path))
    try:
        domain = importlib.import_module("domain")
        assert callable(domain.domain_spec.get_tutorial)
        assert len(domain.get_tutorial().steps) == 2
    finally:
        if str(tmp_path) in sys.path:
            sys.path.remove(str(tmp_path))
        sys.modules.pop("domain", None)


def test_init_without_tutorial_flag_keeps_the_scaffold_lean(tmp_path):
    import importlib

    from semente.manifest import Manifest

    _scaffold(tmp_path)

    assert "tutorial" not in Manifest.load(tmp_path / "semente.yaml").features
    assert not (tmp_path / "domain" / "tutorial.py").exists()

    sys.modules.pop("domain", None)
    sys.path.insert(0, str(tmp_path))
    try:
        domain = importlib.import_module("domain")
        assert domain.domain_spec.get_tutorial is None
    finally:
        if str(tmp_path) in sys.path:
            sys.path.remove(str(tmp_path))
        sys.modules.pop("domain", None)


def test_init_tutorial_interactive_prompt_accepts(tmp_path, monkeypatch):
    from semente.manifest import Manifest

    monkeypatch.setattr("builtins.input", _answers("", "y"))

    code = cmd_init(directory=str(tmp_path), stdin=_TTY())

    assert code == 0
    assert Manifest.load(tmp_path / "semente.yaml").features["tutorial"] is True
    assert (tmp_path / "domain" / "tutorial.py").exists()


def test_init_tutorial_interactive_prompt_declines(tmp_path, monkeypatch):
    from semente.manifest import Manifest

    monkeypatch.setattr("builtins.input", _answers("", ""))

    code = cmd_init(directory=str(tmp_path), stdin=_TTY())

    assert code == 0
    assert "tutorial" not in Manifest.load(tmp_path / "semente.yaml").features
    assert not (tmp_path / "domain" / "tutorial.py").exists()