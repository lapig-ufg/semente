"""CLI wiring: launch --demo flag, wizard pre-flight, manifest check, parser."""

import pytest

import semente.cli as cli
from semente.cli import launcher
from semente.cli.launcher import run_streamlit


@pytest.fixture(autouse=True)
def _complete_env(monkeypatch):
    """Skip the wizard in every CLI test (it has its own test file)."""
    monkeypatch.setenv("PRIMARY_MODEL_PROVIDER", "google")
    monkeypatch.setenv("PRIMARY_MODEL_ID", "gemini-3.5-flash-lite")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")


def test_launch_streamlit_demo_sets_env(monkeypatch, tmp_path):
    """launch streamlit --demo: SEMENTE_DEMO=1 in the child env, no manifest needed."""
    captured = {}

    def fake_run(cmd, env=None):
        captured["cmd"] = cmd
        captured["env"] = env

    monkeypatch.setattr(launcher.subprocess, "run", fake_run)
    monkeypatch.chdir(tmp_path)  # no semente.yaml here

    run_streamlit(demo=True)

    assert captured["env"]["SEMENTE_DEMO"] == "1"
    assert any("streamlit_webapp.py" in str(c) for c in captured["cmd"])


def test_launch_streamlit_plain_with_manifest(monkeypatch, tmp_path):
    """Plain launch: no SEMENTE_DEMO when a manifest exists."""
    captured = {}

    def fake_run(cmd, env=None):
        captured["env"] = env

    monkeypatch.setattr(launcher.subprocess, "run", fake_run)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "semente.yaml").write_text("name: test\n")

    run_streamlit(demo=False)

    assert captured["env"] is not None
    assert "SEMENTE_DEMO" not in captured["env"]


def test_launch_streamlit_env_manifest_var(monkeypatch, tmp_path):
    """SEMENTE_MANIFEST pointing at an existing file is accepted."""
    captured = {}

    def fake_run(cmd, env=None):
        captured["env"] = env

    monkeypatch.setattr(launcher.subprocess, "run", fake_run)
    manifest = tmp_path / "app.yaml"
    manifest.write_text("name: test\n")
    monkeypatch.setenv("SEMENTE_MANIFEST", str(manifest))
    monkeypatch.chdir(tmp_path)

    run_streamlit(demo=False)

    assert "SEMENTE_DEMO" not in captured["env"]


def test_launch_streamlit_without_manifest_exits_with_hint(monkeypatch, tmp_path):
    """Plain launch with no manifest: exit with a message suggesting --demo."""
    monkeypatch.setattr(launcher.subprocess, "run", lambda *a, **k: pytest.fail("must not launch"))
    monkeypatch.chdir(tmp_path)  # no semente.yaml
    monkeypatch.delenv("SEMENTE_MANIFEST", raising=False)

    with pytest.raises(SystemExit) as exc:
        run_streamlit(demo=False)

    assert "--demo" in str(exc.value.code)


def test_launch_streamlit_demo_runs_wizard_first(monkeypatch, tmp_path):
    """--demo still goes through the env pre-flight (the wizard)."""
    called = {"count": 0}

    def fake_ensure():
        called["count"] += 1
        return []

    monkeypatch.setattr("semente.configs.wizard.ensure_config", fake_ensure)
    monkeypatch.setattr(launcher.subprocess, "run", lambda cmd, env=None: None)

    run_streamlit(demo=True)

    assert called["count"] == 1


def test_launch_whatsapp_exits_with_hint(capsys):
    """whatsapp is a webhook channel: the launcher explains, does not run."""
    with pytest.raises(SystemExit) as exc:
        launcher.cmd_launch("whatsapp")
    assert "main.py" in str(exc.value.code)


def test_parser_wiring():
    """The real parser: every command parses to the right shape."""
    parser = cli.build_parser()

    args = parser.parse_args(["launch", "streamlit", "--demo"])
    assert args.command == "launch" and args.interface == "streamlit" and args.demo

    args = parser.parse_args(["launch", "streamlit"])
    assert args.demo is False

    args = parser.parse_args(["init", "my-app", "--provider", "ollama", "--force"])
    assert args.directory == "my-app"
    assert args.provider == "ollama"
    assert args.force and args.non_interactive is False

    args = parser.parse_args(["config", "enable", "tts"])
    assert args.config_command == "enable" and args.feature == "tts"

    args = parser.parse_args(["config", "channel", "add", "whatsapp"])
    assert args.channel_command == "add" and args.name == "whatsapp"

    args = parser.parse_args(["status"])
    assert args.command == "status"


def test_parser_rejects_legacy_streamlit():
    """The old 'semente streamlit' command is gone."""
    parser = cli.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["streamlit"])