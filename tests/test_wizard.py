"""Wizard pre-flight: missing-key detection, .env merge, skip logic."""

import os
from pathlib import Path

from semente.configs import wizard


def test_get_missing_all_absent(monkeypatch):
    """No env at all -> the full google block is missing."""
    for key in ("PRIMARY_MODEL_PROVIDER", "PRIMARY_MODEL_ID", "GOOGLE_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    missing = wizard.get_missing({})
    assert missing == ["PRIMARY_MODEL_PROVIDER", "PRIMARY_MODEL_ID", "GOOGLE_API_KEY"]


def test_get_missing_ollama_block(monkeypatch):
    """Ollama provider requires host + key instead of the google key."""
    monkeypatch.delenv("PRIMARY_MODEL_PROVIDER", raising=False)
    env = {
        "PRIMARY_MODEL_PROVIDER": "ollama",
        "PRIMARY_MODEL_ID": "gemma4:31b-cloud",
        "OLLAMA_HOST": "http://localhost:11434",
    }
    assert wizard.get_missing(env) == ["OLLAMA_API_KEY"]


def test_get_missing_nothing(monkeypatch):
    """Complete model block -> no wizard."""
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    env = {
        "PRIMARY_MODEL_PROVIDER": "google",
        "PRIMARY_MODEL_ID": "gemini-3.5-flash-lite",
        "GOOGLE_API_KEY": "x",
    }
    assert wizard.get_missing(env) == []


def test_effective_env_shell_wins(tmp_path, monkeypatch):
    """Exported shell vars count as set even with no .env file."""
    monkeypatch.setenv("PRIMARY_MODEL_PROVIDER", "google")
    monkeypatch.setenv("PRIMARY_MODEL_ID", "gemini-3.5-flash-lite")
    monkeypatch.setenv("GOOGLE_API_KEY", "from-shell")
    env_path = tmp_path / ".env"
    env_path.write_text("GOOGLE_API_KEY=from-file\n")
    env = wizard.effective_env(env_path)
    assert env["GOOGLE_API_KEY"] == "from-shell"
    assert wizard.get_missing(env) == []


def test_effective_env_file_fills_gaps(tmp_path, monkeypatch):
    """.env values count when the shell does not export them."""
    monkeypatch.delenv("PRIMARY_MODEL_ID", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    env_path = tmp_path / ".env"
    env_path.write_text("PRIMARY_MODEL_ID=m\nGOOGLE_API_KEY=k\n")
    env = wizard.effective_env(env_path)
    assert wizard.get_missing(env) == ["PRIMARY_MODEL_PROVIDER"]


def test_run_wizard_asks_only_missing_google():
    """Full wizard on empty env: provider, model id, key."""
    answers = wizard.run_wizard(
        ["PRIMARY_MODEL_PROVIDER", "PRIMARY_MODEL_ID", "GOOGLE_API_KEY"],
        {},
        input_fn=lambda prompt: "",
        getpass_fn=lambda prompt: "secret-key",
    )
    by_key = {a["key"]: a["value"] for a in answers}
    assert by_key["PRIMARY_MODEL_PROVIDER"] == "google"
    assert by_key["PRIMARY_MODEL_ID"] == "gemini-3.5-flash-lite"
    assert by_key["GOOGLE_API_KEY"] == "secret-key"


def test_run_wizard_ollama_defaults():
    """Choosing ollama asks for host + key and uses the ollama model default."""
    inputs = iter(["ollama", "", "http://localhost:11434"])
    answers = wizard.run_wizard(
        ["PRIMARY_MODEL_PROVIDER", "PRIMARY_MODEL_ID", "OLLAMA_HOST", "OLLAMA_API_KEY"],
        {},
        input_fn=lambda prompt: next(inputs),
        getpass_fn=lambda prompt: "ollama-key",
    )
    by_key = {a["key"]: a["value"] for a in answers}
    assert by_key["PRIMARY_MODEL_PROVIDER"] == "ollama"
    assert by_key["PRIMARY_MODEL_ID"] == "gemma4:31b-cloud"
    assert by_key["OLLAMA_HOST"] == "http://localhost:11434"
    assert by_key["OLLAMA_API_KEY"] == "ollama-key"


def test_run_wizard_partial_env(monkeypatch):
    """Provider + model already set -> only the key is asked."""
    env = {"PRIMARY_MODEL_PROVIDER": "google", "PRIMARY_MODEL_ID": "gemini-3.5-flash-lite"}
    answers = wizard.run_wizard(
        wizard.get_missing(env),
        env,
        input_fn=lambda prompt: (_ for _ in ()).throw(AssertionError(f"should not ask: {prompt}")),
        getpass_fn=lambda prompt: "key",
    )
    assert answers == [{"key": "GOOGLE_API_KEY", "value": "key"}]


def test_save_to_env_file_preserves_lines(tmp_path):
    """Existing keys replaced in place, comments/other keys kept, new keys appended."""
    env_path = tmp_path / ".env"
    env_path.write_text(
        "# my app config\n"
        "APP_ENV=development\n"
        "GOOGLE_API_KEY=old\n"
        "\n"
        "EXTRA=value\n"
    )
    wizard.save_to_env_file(
        env_path,
        [
            {"key": "GOOGLE_API_KEY", "value": "new"},
            {"key": "PRIMARY_MODEL_ID", "value": "m"},
        ],
    )
    content = env_path.read_text(encoding="utf-8")
    assert "# my app config" in content
    assert "APP_ENV=development" in content
    assert "GOOGLE_API_KEY=new" in content
    assert "GOOGLE_API_KEY=old" not in content
    assert "PRIMARY_MODEL_ID=m" in content
    assert "EXTRA=value" in content


def test_save_to_env_file_creates(tmp_path):
    """No existing .env -> a new one is created."""
    env_path = tmp_path / ".env"
    wizard.save_to_env_file(env_path, [{"key": "GOOGLE_API_KEY", "value": "k"}])
    assert env_path.read_text(encoding="utf-8") == "GOOGLE_API_KEY=k\n"


def test_ensure_config_noop_when_complete(tmp_path, monkeypatch):
    """Complete effective env -> no prompts, no write."""
    monkeypatch.setenv("PRIMARY_MODEL_PROVIDER", "google")
    monkeypatch.setenv("PRIMARY_MODEL_ID", "gemini-3.5-flash-lite")
    monkeypatch.setenv("GOOGLE_API_KEY", "k")
    env_path = tmp_path / ".env"

    class NoTTY:
        def isatty(self):
            raise AssertionError("should not be consulted when nothing is missing")

    answers = wizard.ensure_config(env_path, stdin=NoTTY())
    assert answers == []
    assert not env_path.exists()


def test_ensure_config_writes_and_exports(tmp_path, monkeypatch):
    """Missing values -> wizard runs, .env saved, os.environ exported."""
    for key in ("PRIMARY_MODEL_PROVIDER", "PRIMARY_MODEL_ID", "GOOGLE_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    env_path = tmp_path / ".env"

    class TTY:
        def isatty(self):
            return True

    answers = wizard.ensure_config(
        env_path,
        stdin=TTY(),
        input_fn=lambda prompt: "",
        getpass_fn=lambda prompt: "wizard-key",
    )
    by_key = {a["key"]: a["value"] for a in answers}
    assert by_key["GOOGLE_API_KEY"] == "wizard-key"
    assert "GOOGLE_API_KEY=wizard-key" in env_path.read_text(encoding="utf-8")
    assert os.environ["GOOGLE_API_KEY"] == "wizard-key"


def test_ensure_config_non_tty_warns_and_skips(tmp_path, monkeypatch, capsys):
    """Docker/CI (no TTY): warn, no prompts, no file write, launch proceeds."""
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    env_path = tmp_path / ".env"

    class NoTTY:
        def isatty(self):
            return False

    answers = wizard.ensure_config(env_path, stdin=NoTTY())
    assert answers == []
    assert not env_path.exists()
    assert "GOOGLE_API_KEY" in capsys.readouterr().out


def test_ensure_config_env_file_gap_only(tmp_path, monkeypatch):
    """.env with most values -> wizard asks only for the gap and merges."""
    monkeypatch.delenv("PRIMARY_MODEL_ID", raising=False)
    monkeypatch.setenv("PRIMARY_MODEL_PROVIDER", "google")
    monkeypatch.setenv("GOOGLE_API_KEY", "already-set")
    env_path = tmp_path / ".env"
    env_path.write_text("APP_ENV=development\n")

    class TTY:
        def isatty(self):
            return True

    def input_fn(prompt):
        assert "Model ID" in prompt
        return "gemini-2.0-flash"

    wizard.ensure_config(env_path, stdin=TTY(), input_fn=input_fn, getpass_fn=getpass_fail)
    content = env_path.read_text(encoding="utf-8")
    assert "APP_ENV=development" in content
    assert "PRIMARY_MODEL_ID=gemini-2.0-flash" in content


def getpass_fail(prompt):
    raise AssertionError(f"should not ask for a secret: {prompt}")