"""semente config: features, models, channels, validation, errors."""

import pytest

from semente.cli import config_cmd
from semente.manifest import Manifest


@pytest.fixture
def app_dir(tmp_path, monkeypatch):
    """A scaffolded app directory with a clean manifest, cwd inside it."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SEMENTE_MANIFEST", raising=False)
    Manifest(name="test-app").save(tmp_path / "semente.yaml")
    return tmp_path


def _manifest(app_dir):
    return Manifest.load(app_dir / "semente.yaml")


def test_enable_disable_roundtrip(app_dir, capsys):
    config_cmd.cmd_config_disable("tts")
    assert _manifest(app_dir).features["tts"] is False
    assert "disabled" in capsys.readouterr().out

    config_cmd.cmd_config_enable("tts")
    assert _manifest(app_dir).features["tts"] is True
    assert "enabled" in capsys.readouterr().out


def test_enable_unknown_feature_exits(app_dir):
    with pytest.raises(SystemExit) as exc:
        config_cmd.cmd_config_enable("weather")
    assert "tts" in str(exc.value.code)  # the message lists valid features


def test_set_simple_key(app_dir):
    config_cmd.cmd_config_set("language", "pt-BR")
    assert _manifest(app_dir).language == "pt-BR"


def test_set_engine_validated(app_dir):
    from semente.cli.config_cmd import KNOWN_ENGINES

    with pytest.raises(SystemExit):
        config_cmd.cmd_config_set("engine", "gpt4")
    config_cmd.cmd_config_set("engine", "bare")
    assert _manifest(app_dir).engine == "bare"
    assert KNOWN_ENGINES == ["agno", "adk", "bare"]


def test_set_model_keys(app_dir):
    config_cmd.cmd_config_set("models.primary.id", "gemini-2.0-flash")
    config_cmd.cmd_config_set("models.fallback.provider", "ollama")
    manifest = _manifest(app_dir)
    assert manifest.models["primary"]["id"] == "gemini-2.0-flash"
    assert manifest.models["fallback"]["provider"] == "ollama"


def test_set_model_provider_validated(app_dir):
    with pytest.raises(SystemExit):
        config_cmd.cmd_config_set("models.primary.provider", "anthropic")


def test_set_unknown_key_exits(app_dir):
    with pytest.raises(SystemExit):
        config_cmd.cmd_config_set("nonexistent.key", "x")


def test_channel_add_remove(app_dir, capsys):
    config_cmd.cmd_config_channel_add("whatsapp")
    assert _manifest(app_dir).channels == ["streamlit", "whatsapp"]

    # Idempotent add.
    config_cmd.cmd_config_channel_add("whatsapp")
    assert _manifest(app_dir).channels == ["streamlit", "whatsapp"]

    config_cmd.cmd_config_channel_remove("streamlit")
    assert _manifest(app_dir).channels == ["whatsapp"]


def test_channel_unknown_exits(app_dir):
    with pytest.raises(SystemExit):
        config_cmd.cmd_config_channel_add("telegram")


def test_channel_remove_absent_is_friendly(app_dir, capsys):
    config_cmd.cmd_config_channel_remove("whatsapp")
    assert "not enabled" in capsys.readouterr().out


def test_missing_manifest_exits(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SEMENTE_MANIFEST", raising=False)
    with pytest.raises(SystemExit) as exc:
        config_cmd.cmd_config_enable("tts")
    assert "semente init" in str(exc.value.code)


def test_semente_manifest_env_var_wins(tmp_path, monkeypatch):
    """SEMENTE_MANIFEST points the editor at another manifest file."""
    monkeypatch.chdir(tmp_path)
    custom = tmp_path / "custom.yaml"
    Manifest(name="custom-app").save(custom)
    monkeypatch.setenv("SEMENTE_MANIFEST", str(custom))
    config_cmd.cmd_config_set("language", "es")
    assert Manifest.load(custom).language == "es"