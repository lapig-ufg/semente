"""semente provider: primary/fallback manifest config, API keys into .env, ls."""

import pytest

from semente.cli import provider_cmd
from semente.cli.provider_cmd import KNOWN_PROVIDERS
from semente.manifest import Manifest


@pytest.fixture
def app_dir(tmp_path, monkeypatch):
    """A scaffolded app directory with no manifest model override, cwd inside it.

    The .env-based keys are neutralized (chdir keeps DEFAULT_ENV_PATH empty).
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SEMENTE_MANIFEST", raising=False)
    for var in (
        "PRIMARY_MODEL_PROVIDER",
        "PRIMARY_MODEL_ID",
        "FALLBACK_MODEL_PROVIDER",
        "FALLBACK_MODEL_ID",
        "GOOGLE_API_KEY",
        "OLLAMA_API_KEY",
        "OLLAMA_HOST",
    ):
        monkeypatch.delenv(var, raising=False)
    Manifest(name="test-app").save(tmp_path / "semente.yaml")
    return tmp_path


def _manifest(app_dir):
    return Manifest.load(app_dir / "semente.yaml")


def test_catalog_matches_wizard_key_blocks():
    assert KNOWN_PROVIDERS == ["google", "ollama"]


def test_primary_writes_manifest_override(app_dir):
    provider_cmd.cmd_provider_primary("google", model="gemini-2.0-flash")
    manifest = _manifest(app_dir)
    assert manifest.models["primary"] == {"provider": "google", "id": "gemini-2.0-flash"}


def test_primary_invalid_provider_exits(app_dir):
    with pytest.raises(SystemExit) as exc:
        provider_cmd.cmd_provider_primary("anthropic")
    assert "google" in str(exc.value.code)  # the message lists valid providers


def test_primary_without_model_keeps_id(app_dir, capsys):
    provider_cmd.cmd_provider_primary("ollama")
    manifest = _manifest(app_dir)
    assert manifest.models["primary"]["provider"] == "ollama"
    assert "id" not in manifest.models["primary"]
    assert "untouched" in capsys.readouterr().out


def test_fallback_sets_and_removes(app_dir):
    provider_cmd.cmd_provider_fallback("ollama", model="gemma4:31b-cloud")
    manifest = _manifest(app_dir)
    assert manifest.models["fallback"] == {"provider": "ollama", "id": "gemma4:31b-cloud"}

    provider_cmd.cmd_provider_fallback(None, disable=True)
    manifest = _manifest(app_dir)
    assert "fallback" not in manifest.models


def test_fallback_remove_when_absent_is_friendly(app_dir, capsys):
    provider_cmd.cmd_provider_fallback(None, disable=True)
    assert "already" in capsys.readouterr().out


def test_fallback_sames_provider_warns(app_dir, capsys):
    provider_cmd.cmd_provider_primary("google")
    provider_cmd.cmd_provider_fallback("google")
    assert "Note" in capsys.readouterr().out or "same provider" in capsys.readouterr().out


def test_fallback_without_args_shows_status_and_hints(app_dir, capsys):
    provider_cmd.cmd_provider_fallback(None)
    out = capsys.readouterr().out
    assert "No fallback" in out
    assert "provider fallback <provider>" in out
    assert "fallback --disable" in out


def test_key_writes_env_secret_and_masks_it(app_dir, capsys, monkeypatch):
    monkeypatch.setattr(provider_cmd, "getpass", lambda prompt: "super-secret-key")
    provider_cmd.cmd_provider_key("google")
    env_text = (app_dir / ".env").read_text(encoding="utf-8")
    assert "GOOGLE_API_KEY=super-secret-key" in env_text
    assert "super-secret-key" not in capsys.readouterr().out  # masked on screen


def test_key_empty_keeps_unset(app_dir, capsys, monkeypatch):
    monkeypatch.setattr(provider_cmd, "getpass", lambda prompt: "")
    provider_cmd.cmd_provider_key("google")
    assert not (app_dir / ".env").exists()
    assert "Nothing to write" in capsys.readouterr().out


def test_key_existing_value_preserved(app_dir, monkeypatch):
    (app_dir / ".env").write_text("GOOGLE_API_KEY=old-secret\n", encoding="utf-8")
    monkeypatch.setattr(provider_cmd, "getpass", lambda prompt: "")
    provider_cmd.cmd_provider_key("google")
    assert "old-secret" in (app_dir / ".env").read_text(encoding="utf-8")


def test_key_ollama_sets_host_and_api_key(app_dir, monkeypatch):
    answers = iter(["http://localhost:9999", "local"])
    monkeypatch.setattr(provider_cmd, "input", lambda *a, **k: next(answers), raising=False)
    monkeypatch.setattr(provider_cmd, "getpass", lambda prompt: "local")
    provider_cmd.cmd_provider_key("ollama")
    text = (app_dir / ".env").read_text(encoding="utf-8")
    assert "OLLAMA_HOST=http://localhost:9999" in text
    assert "OLLAMA_API_KEY=local" in text


def test_invalid_provider_for_key_exits(app_dir):
    with pytest.raises(SystemExit):
        provider_cmd.cmd_provider_key("anthropic")


def test_ls_reports_missing_keys(app_dir, monkeypatch):
    import io

    from rich.console import Console

    provider_cmd.cmd_provider_primary("google")
    out_stream = io.StringIO()
    console = Console(file=out_stream, width=180, force_terminal=False)
    monkeypatch.setattr(provider_cmd, "console", console)
    provider_cmd.cmd_provider_ls()
    out = out_stream.getvalue()
    assert "google" in out
    assert "missing" in out  # GOOGLE_API_KEY not set
    assert "fallback" in out and "none" in out.lower()


def test_missing_manifest_exits(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SEMENTE_MANIFEST", raising=False)
    with pytest.raises(SystemExit) as exc:
        provider_cmd.cmd_provider_primary("google")
    assert "semente init" in str(exc.value.code)