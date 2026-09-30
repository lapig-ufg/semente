"""semente status: tables, env health, doctor checks, missing manifest."""

import pytest
from rich.console import Console

from semente.cli import status_cmd


@pytest.fixture
def app_dir(tmp_path, monkeypatch):
    """An app dir with manifest + a scaffold-like domain module."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SEMENTE_MANIFEST", raising=False)
    (tmp_path / "semente.yaml").write_text(
        "name: status-app\n"
        "language: en\n"
        "domain_module: domain\n"
        "prompts_dir: domain/prompts\n"
        "channels: [streamlit, whatsapp]\n"
        "features:\n"
        "  tts: false\n"
    )
    domain = tmp_path / "domain"
    domain.mkdir()
    (domain / "__init__.py").write_text("from semente.domain import DomainSpec\n\n\ndomain_spec = DomainSpec(name='x')\n")
    return tmp_path


def _capture_status(monkeypatch):
    """Run cmd_status with a rich Console that renders to a plain string."""
    from semente.cli import status_cmd as sc

    output = []
    console = Console(record=True, width=200, file=_CaptureFile(output), force_terminal=False)
    monkeypatch.setattr("semente.cli.status_cmd.Console", lambda: console)
    sc.cmd_status()
    return "".join(output)


class _CaptureFile:
    def __init__(self, sink):
        self.sink = sink

    def write(self, text):
        self.sink.append(text)

    def flush(self):
        pass

    def isatty(self):
        return False


def test_status_shows_app_and_features(app_dir, monkeypatch):
    out = _capture_status(monkeypatch)
    assert "status-app" in out
    assert "tts" in out
    assert "whatsapp" in out
    assert "domain" in out


def test_status_shows_disabled_feature(app_dir, monkeypatch):
    out = _capture_status(monkeypatch)
    assert "disabled" in out  # tts: false in the fixture manifest


def test_status_env_health(app_dir, monkeypatch):
    monkeypatch.setenv("PRIMARY_MODEL_PROVIDER", "google")
    monkeypatch.setenv("PRIMARY_MODEL_ID", "m")
    monkeypatch.setenv("GOOGLE_API_KEY", "abcdefghij")
    out = _capture_status(monkeypatch)
    assert "abc...hij" in out  # masked key
    assert "missing" not in out


def test_status_env_missing(app_dir, monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    out = _capture_status(monkeypatch)
    assert "missing" in out


def test_status_doctor_domain_ok(app_dir, monkeypatch):
    out = _capture_status(monkeypatch)
    assert "OK" in out
    assert "domain_spec" in out


def test_status_doctor_domain_missing(tmp_path, monkeypatch):
    """Manifest points at a domain module that doesn't exist."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SEMENTE_MANIFEST", raising=False)
    (tmp_path / "semente.yaml").write_text("name: x\n")
    out = _capture_status(monkeypatch)
    assert "FAIL" in out
    assert "not found" in out


def test_status_no_manifest(tmp_path, monkeypatch, capsys):
    """No manifest: friendly hint, exit 0."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SEMENTE_MANIFEST", raising=False)
    code = status_cmd.cmd_status()
    assert code == 0
    out = capsys.readouterr().out
    assert "semente init" in out