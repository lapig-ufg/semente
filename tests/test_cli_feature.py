"""semente feature: catalog, ls, actives, add (scaffold + enable), flags, errors."""

import pytest

from semente.cli import feature_cmd
from semente.cli.feature_cmd import FEATURES, KNOWN_FEATURES, _feature_status
from semente.manifest import FeedbackConfig, Manifest, TermsConfig


@pytest.fixture
def app_dir(tmp_path, monkeypatch):
    """A scaffolded app directory with a clean manifest, cwd inside it."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SEMENTE_MANIFEST", raising=False)
    Manifest(name="test-app").save(tmp_path / "semente.yaml")
    return tmp_path


def _manifest(app_dir):
    return Manifest.load(app_dir / "semente.yaml")


def test_catalog_is_the_single_source():
    """KNOWN_FEATURES mirrors the FEATURES catalog; guardrails scaffolds."""
    assert KNOWN_FEATURES == list(FEATURES)
    assert [f.name for f in FEATURES.values()] == [
        "tts",
        "summarization",
        "interaction-assessment",
        "guardrails",
        "terms-acceptance",
    ]
    assert {f.name for f in FEATURES.values() if f.scaffold} == {
        "guardrails",
        "terms-acceptance",
    }
    assert {f.name for f in FEATURES.values() if not f.default_enabled} == {"terms-acceptance"}


def test_flag_toggle_roundtrip(app_dir, capsys):
    feature_cmd.cmd_feature_toggle("tts", False)
    assert _manifest(app_dir).features["tts"] is False
    assert "disabled" in capsys.readouterr().out

    feature_cmd.cmd_feature_toggle("tts", True)
    assert _manifest(app_dir).features["tts"] is True
    assert "enabled" in capsys.readouterr().out


def test_disable_leaves_code_alone(app_dir):
    """disable only edits the manifest — it must not delete/move any file."""
    before = sorted(p.name for p in app_dir.rglob("*"))
    feature_cmd.cmd_feature_toggle("summarization", False)
    assert sorted(p.name for p in app_dir.rglob("*")) == before


def test_toggle_without_flag_shows_status_and_both_hints(app_dir, capsys):
    feature_cmd.cmd_feature_toggle("tts", None)
    out = capsys.readouterr().out
    assert "tts" in out
    assert "--enable" in out and "--disable" in out  # both options hinted


def test_toggle_interaction_assessment_preserves_window_size(app_dir):
    manifest, path = feature_cmd.load_manifest_or_exit()
    manifest.features = {"interaction-assessment": FeedbackConfig(enable=False, window_size=9)}
    manifest.save(path)
    feature_cmd.cmd_feature_toggle("interaction-assessment", True)
    saved = _manifest(app_dir).features["interaction-assessment"]
    assert isinstance(saved, FeedbackConfig)
    assert saved.enable is True
    assert saved.window_size == 9


def test_ls_lists_all_features_with_status(app_dir, monkeypatch):
    import io

    from rich.console import Console

    feature_cmd.cmd_feature_toggle("guardrails", False)
    out_stream = io.StringIO()
    console = Console(file=out_stream, width=180, force_terminal=False)
    monkeypatch.setattr(feature_cmd, "console", console)
    feature_cmd.cmd_feature_ls()
    out = out_stream.getvalue()
    for name in FEATURES:
        assert name in out
    assert "disabled" in out  # guardrails was disabled above
    assert "default (on)" in out  # tts is absent from the manifest


def test_actives_lists_enabled_and_defaults(app_dir, monkeypatch):
    import io

    from rich.console import Console

    feature_cmd.cmd_feature_toggle("guardrails", False)
    out_stream = io.StringIO()
    console = Console(file=out_stream, width=180, force_terminal=False)
    monkeypatch.setattr(feature_cmd, "console", console)
    feature_cmd.cmd_feature_actives()
    out = out_stream.getvalue()
    assert "tts" in out and "summarization" in out  # defaults count as active
    assert "guardrails" not in out or "Active" not in out.split("guardrails")[0]  # excluded
    assert "interaction-assessment" in out
    assert "terms-acceptance" not in out  # default off


def test_terms_acceptance_defaults_off(app_dir, capsys):
    feature_cmd.cmd_feature_toggle("terms-acceptance", None)
    assert "default (off)" in capsys.readouterr().out

    feature_cmd.cmd_feature_toggle("terms-acceptance", True)
    manifest = _manifest(app_dir)
    assert isinstance(manifest.features["terms-acceptance"], TermsConfig)
    assert manifest.features["terms-acceptance"].enable is True


def test_terms_toggle_preserves_file_and_url(app_dir):
    manifest, path = feature_cmd.load_manifest_or_exit()
    manifest.features = {
        "terms-acceptance": TermsConfig(enable=True, file="domain/terms.md", url="https://x.test/t")
    }
    manifest.save(path)

    feature_cmd.cmd_feature_toggle("terms-acceptance", False)
    saved = _manifest(app_dir).features["terms-acceptance"]
    assert isinstance(saved, TermsConfig)
    assert saved.enable is False
    assert saved.file == "domain/terms.md"
    assert saved.url == "https://x.test/t"

    feature_cmd.cmd_feature_toggle("terms-acceptance", True)
    assert _manifest(app_dir).features["terms-acceptance"].enable is True


def test_first_enable_scaffolds_and_configures_terms(app_dir, capsys):
    feature_cmd.cmd_feature_toggle("terms-acceptance", True)
    out = capsys.readouterr().out

    example = app_dir / "domain" / "terms_example.md"
    assert example.exists()
    assert "Scaffolded example" in out
    content = example.read_text(encoding="utf-8")
    assert "Terms of Use" in content
    assert "test-app" in content  # the manifest app name

    cfg = _manifest(app_dir).features["terms-acceptance"]
    assert cfg.enable is True
    assert cfg.file == "domain/terms_example.md"
    assert cfg.url == ""


def test_second_enable_does_not_overwrite_the_terms_file(app_dir):
    feature_cmd.cmd_feature_toggle("terms-acceptance", True)
    example = app_dir / "domain" / "terms_example.md"
    example.write_text("# our own terms\n", encoding="utf-8")

    feature_cmd.cmd_feature_toggle("terms-acceptance", True)
    assert example.read_text(encoding="utf-8") == "# our own terms\n"
    assert _manifest(app_dir).features["terms-acceptance"].file == "domain/terms_example.md"

    feature_cmd.cmd_feature_toggle("terms-acceptance", False)
    assert example.exists()  # disable never deletes app files


def test_enable_respects_a_configured_terms_file(app_dir):
    (app_dir / "domain").mkdir(exist_ok=True)
    (app_dir / "domain" / "mine.md").write_text("mine", encoding="utf-8")
    manifest, path = feature_cmd.load_manifest_or_exit()
    manifest.features = {"terms-acceptance": TermsConfig(enable=False, file="domain/mine.md")}
    manifest.save(path)

    feature_cmd.cmd_feature_toggle("terms-acceptance", True)
    assert not (app_dir / "domain" / "terms_example.md").exists()
    assert _manifest(app_dir).features["terms-acceptance"].file == "domain/mine.md"


def test_enable_warns_when_configured_terms_file_is_missing(app_dir, capsys):
    manifest, path = feature_cmd.load_manifest_or_exit()
    manifest.features = {"terms-acceptance": TermsConfig(enable=False, file="domain/nope.md")}
    manifest.save(path)

    feature_cmd.cmd_feature_toggle("terms-acceptance", True)
    assert "does not exist" in capsys.readouterr().out
    assert _manifest(app_dir).features["terms-acceptance"].file == "domain/nope.md"


def test_add_terms_acceptance_scaffolds_and_enables(app_dir):
    feature_cmd.cmd_feature_add("terms-acceptance")
    assert (app_dir / "domain" / "terms_example.md").exists()
    cfg = _manifest(app_dir).features["terms-acceptance"]
    assert cfg.enable is True
    assert cfg.file == "domain/terms_example.md"


def test_scaffold_path_is_relative_to_a_nested_manifest(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SEMENTE_MANIFEST", raising=False)
    nested = tmp_path / "apps" / "x"
    nested.mkdir(parents=True)
    Manifest(name="nested-app").save(nested / "semente.yaml")
    monkeypatch.setenv("SEMENTE_MANIFEST", "apps/x/semente.yaml")

    feature_cmd.cmd_feature_toggle("terms-acceptance", True)

    cfg = Manifest.load(nested / "semente.yaml").features["terms-acceptance"]
    assert cfg.file == "domain/terms_example.md"
    assert (nested / "domain" / "terms_example.md").exists()


def test_add_guardrails_scaffolds_and_enables(app_dir):
    feature_cmd.cmd_feature_add("guardrails")
    example = app_dir / "domain" / "guardrails_example.py"
    assert example.exists()
    assert "GUARDRAILS" in example.read_text(encoding="utf-8")
    manifest = _manifest(app_dir)
    assert manifest.features["guardrails"] is True

    # The scaffolded module must be a valid, importable engine-free file.
    src = example.read_text(encoding="utf-8")
    assert "agno" not in src


def test_add_guardrails_is_idempotent(app_dir, capsys):
    feature_cmd.cmd_feature_add("guardrails")
    feature_cmd.cmd_feature_add("guardrails")
    assert "already exists" in capsys.readouterr().out


def test_add_framework_internal_feature_only_enables(app_dir, capsys):
    feature_cmd.cmd_feature_add("tts")
    assert "framework-internal" in capsys.readouterr().out
    assert _manifest(app_dir).features["tts"] is True
    assert not (app_dir / "domain" / "guardrails_example.py").exists()


def test_unknown_feature_exits(app_dir):
    with pytest.raises(SystemExit) as exc:
        feature_cmd.cmd_feature_toggle("weather", True)
    assert "tts" in str(exc.value.code)  # the message lists valid features


def test_missing_manifest_exits(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SEMENTE_MANIFEST", raising=False)
    with pytest.raises(SystemExit) as exc:
        feature_cmd.cmd_feature_toggle("tts", True)
    assert "semente init" in str(exc.value.code)


def test_status_respects_interaction_assessment_config():
    manifest = Manifest(name="x", features={"interaction-assessment": FeedbackConfig(enable=False)})
    assert _feature_status(manifest, "interaction-assessment") == "disabled"
    manifest.features["interaction-assessment"] = FeedbackConfig(enable=True, window_size=3)
    assert _feature_status(manifest, "interaction-assessment") == "enabled"
    assert _feature_status(manifest, "tts") == "default"