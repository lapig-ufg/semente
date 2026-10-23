"""semente channel: catalog, ls, actives, --enable/--disable flags, status hint."""

import pytest

from semente.cli import channel_cmd
from semente.cli.channel_cmd import CHANNELS, KNOWN_CHANNELS
from semente.manifest import Manifest


@pytest.fixture
def app_dir(tmp_path, monkeypatch):
    """A scaffolded app directory with a clean manifest, cwd inside it."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SEMENTE_MANIFEST", raising=False)
    Manifest(name="test-app").save(tmp_path / "semente.yaml")  # channels: [streamlit]
    return tmp_path


def _manifest(app_dir):
    return Manifest.load(app_dir / "semente.yaml")


def test_catalog():
    assert KNOWN_CHANNELS == list(CHANNELS) == ["streamlit", "whatsapp"]


def test_flag_toggle_roundtrip(app_dir):
    channel_cmd.cmd_channel_toggle("whatsapp", True)
    assert _manifest(app_dir).channels == ["streamlit", "whatsapp"]

    channel_cmd.cmd_channel_toggle("whatsapp", True)  # idempotent
    assert _manifest(app_dir).channels == ["streamlit", "whatsapp"]

    channel_cmd.cmd_channel_toggle("streamlit", False)
    assert _manifest(app_dir).channels == ["whatsapp"]

    channel_cmd.cmd_channel_toggle("whatsapp", False)
    assert _manifest(app_dir).channels == []


def test_toggle_without_flag_shows_status_and_both_hints(app_dir, capsys):
    channel_cmd.cmd_channel_toggle("whatsapp", None)
    out = capsys.readouterr().out
    assert "disabled" in out
    assert "channel whatsapp --enable" in out
    assert "channel whatsapp --disable" in out


def test_ls_lists_all_channels(app_dir, monkeypatch):
    import io

    from rich.console import Console

    out_stream = io.StringIO()
    console = Console(file=out_stream, width=180, force_terminal=False)
    monkeypatch.setattr(channel_cmd, "console", console)
    channel_cmd.cmd_channel_ls()
    out = out_stream.getvalue()
    assert "streamlit" in out and "whatsapp" in out
    assert "enabled" in out and "disabled" in out


def test_actives_lists_enabled_only(app_dir, monkeypatch):
    import io

    from rich.console import Console

    channel_cmd.cmd_channel_toggle("whatsapp", True)
    out_stream = io.StringIO()
    console = Console(file=out_stream, width=180, force_terminal=False)
    monkeypatch.setattr(channel_cmd, "console", console)
    channel_cmd.cmd_channel_actives()
    assert "streamlit" in out_stream.getvalue()
    # disabled channel is not listed as active
    channel_cmd.cmd_channel_toggle("streamlit", False)
    out_stream.truncate(0)
    out_stream.seek(0)
    channel_cmd.cmd_channel_actives()
    assert "streamlit" not in out_stream.getvalue()


def test_unknown_channel_exits(app_dir):
    with pytest.raises(SystemExit) as exc:
        channel_cmd.cmd_channel_toggle("telegram", True)
    assert "streamlit" in str(exc.value.code)  # the message lists valid channels


def test_missing_manifest_exits(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SEMENTE_MANIFEST", raising=False)
    with pytest.raises(SystemExit) as exc:
        channel_cmd.cmd_channel_toggle("whatsapp", True)
    assert "semente init" in str(exc.value.code)


def test_semente_manifest_env_var_wins(tmp_path, monkeypatch):
    """SEMENTE_MANIFEST points the editor at another manifest file."""
    monkeypatch.chdir(tmp_path)
    custom = tmp_path / "custom.yaml"
    Manifest(name="custom-app").save(custom)
    monkeypatch.setenv("SEMENTE_MANIFEST", str(custom))
    channel_cmd.cmd_channel_toggle("whatsapp", True)
    assert Manifest.load(custom).channels == ["streamlit", "whatsapp"]
    assert not (tmp_path / "semente.yaml").exists()