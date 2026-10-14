"""semente config: features, models, channels, validation, errors."""

import sys

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


# ---------------------------------------------------------------------
# Tutorial enablement: flag + scaffolded get_tutorial example
# ---------------------------------------------------------------------


def _domain_package(app_dir, name="test-app"):
    """A domain package in the exact shape ``semente init`` scaffolds."""
    from semente.cli.templates import DOMAIN_INIT_TEMPLATE

    pkg = app_dir / "domain"
    pkg.mkdir(exist_ok=True)
    (pkg / "__init__.py").write_text(DOMAIN_INIT_TEMPLATE.format(name=name), encoding="utf-8")
    return pkg


def test_enable_tutorial_scaffolds_example_and_wires(app_dir):
    pkg = _domain_package(app_dir)
    config_cmd.cmd_config_enable("tutorial")

    assert _manifest(app_dir).features["tutorial"] is True

    init_py = (pkg / "__init__.py").read_text(encoding="utf-8")
    assert "from .tutorial import get_tutorial" in init_py
    assert "get_tutorial=get_tutorial" in init_py
    assert (pkg / "tutorial.py").read_text(encoding="utf-8").count("TutorialStep(") == 2


def test_enabled_tutorial_example_imports_and_runs(app_dir):
    """The scaffolded example is real code: importable and returns a Tutorial."""
    import importlib

    from semente.domain import Tutorial

    _domain_package(app_dir)
    config_cmd.cmd_config_enable("tutorial")

    sys.modules.pop("domain", None)
    sys.path.insert(0, str(app_dir))
    try:
        domain = importlib.import_module("domain")
        tutorial = domain.get_tutorial()
        assert isinstance(tutorial, Tutorial)
        assert len(tutorial.steps) == 2
        assert domain.domain_spec.get_tutorial is domain.get_tutorial
    finally:
        if str(app_dir) in sys.path:
            sys.path.remove(str(app_dir))
        sys.modules.pop("domain", None)


def test_enable_tutorial_idempotent(app_dir, capsys):
    pkg = _domain_package(app_dir)
    config_cmd.cmd_config_enable("tutorial")
    init_source = (pkg / "__init__.py").read_text(encoding="utf-8")
    capsys.readouterr()

    config_cmd.cmd_config_enable("tutorial")
    out = capsys.readouterr().out

    assert "kept" in out and "already wired" in out
    assert (pkg / "__init__.py").read_text(encoding="utf-8") == init_source


def test_enable_tutorial_force_overwrites_the_example(app_dir):
    pkg = _domain_package(app_dir)
    config_cmd.cmd_config_enable("tutorial")
    (pkg / "tutorial.py").write_text("# my custom steps\n", encoding="utf-8")

    config_cmd.cmd_config_enable("tutorial", force=True)

    assert "# my custom steps" not in (pkg / "tutorial.py").read_text(encoding="utf-8")


def test_enable_tutorial_wires_user_modified_spec(app_dir):
    """User-edited specs get the kwarg too — other DomainSpec calls untouched."""
    pkg = _domain_package(app_dir)
    (pkg / "__init__.py").write_text(
        "from semente.domain import DomainSpec\n\n"
        "Other = DomainSpec(name='x')\n\n"
        "domain_spec = DomainSpec(\n"
        "    name='test-app',\n"
        "    tools=[],\n"
        ")\n",
        encoding="utf-8",
    )

    config_cmd.cmd_config_enable("tutorial")

    source = (pkg / "__init__.py").read_text(encoding="utf-8")
    assert "Other = DomainSpec(name='x')" in source  # untouched
    assert "get_tutorial=get_tutorial" not in source.split("domain_spec")[0]
    assert "domain_spec = DomainSpec(\n    name='test-app',\n    tools=[],\n    get_tutorial=get_tutorial,\n)" in source


def test_enable_tutorial_one_line_spec(app_dir):
    """Single-line DomainSpec calls gain an inline kwarg."""
    pkg = _domain_package(app_dir)
    (pkg / "__init__.py").write_text(
        "from semente.domain import DomainSpec\n\n"
        "domain_spec = DomainSpec(name='test-app', tools=[])\n",
        encoding="utf-8",
    )

    config_cmd.cmd_config_enable("tutorial")

    source = (pkg / "__init__.py").read_text(encoding="utf-8")
    assert "DomainSpec(name='test-app', tools=[], get_tutorial=get_tutorial)" in source


def test_enable_tutorial_without_example_module_uses_instructions(app_dir, capsys):
    """A no-spec domain file: example planted, spec untouched, instructions printed."""
    pkg = _domain_package(app_dir)
    (pkg / "__init__.py").write_text(
        "from semente.domain import DomainSpec\n\n"
        "spec = DomainSpec(name='x')\n",
        encoding="utf-8",
    )

    config_cmd.cmd_config_enable("tutorial")
    out = capsys.readouterr().out

    assert (pkg / "tutorial.py").exists()  # the example is planted anyway
    assert "domain_spec = DomainSpec" not in (pkg / "__init__.py").read_text(encoding="utf-8")
    assert "Manual step: domain/__init__.py does not assign domain_spec" in out


def test_enable_tutorial_without_domain_file_keeps_the_flag(app_dir, capsys):
    """No domain module next to the manifest: flag set + actionable hint."""
    config_cmd.cmd_config_enable("tutorial")
    out = capsys.readouterr().out

    assert _manifest(app_dir).features["tutorial"] is True
    assert "not found next to" in out
    assert "domain-api.md" in out


def test_disable_tutorial_only_flips_the_flag(app_dir, capsys):
    """Disabling never deletes user code; it notes that."""
    pkg = _domain_package(app_dir)
    config_cmd.cmd_config_enable("tutorial")
    capsys.readouterr()

    config_cmd.cmd_config_disable("tutorial")
    out = capsys.readouterr().out

    assert _manifest(app_dir).features["tutorial"] is False
    assert (pkg / "tutorial.py").exists()
    assert "stays in place" in out