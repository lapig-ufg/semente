"""Manifest save/load roundtrip, legacy keys, and key stability."""

from pathlib import Path

from semente.manifest import FeedbackConfig, Manifest, TermsConfig


def test_save_load_roundtrip(tmp_path):
    """What save() writes, load() reads back unchanged.

    ``load()`` injects the default ``interaction-assessment`` feature as a
    ``FeedbackConfig`` (with ``enable``/``window_size``) — the roundtrip is
    stable once compared through ``to_dict``.
    """
    path = tmp_path / "semente.yaml"
    manifest = Manifest(
        name="roundtrip",
        language="pt-BR",
        domain_module="domain",
        prompts_dir="domain/prompts",
        engine="bare",
        channels=["streamlit", "whatsapp"],
        features={"tts": True, "summarization": False},
        models={"primary": {"provider": "google", "id": "m"}},
    )
    manifest.save(path)
    loaded = Manifest.load(path)
    assert loaded.name == "roundtrip"
    assert loaded.language == "pt-BR"
    assert loaded.engine == "bare"
    assert loaded.channels == ["streamlit", "whatsapp"]
    assert loaded.features["tts"] is True
    assert loaded.features["summarization"] is False

    assert loaded.features["interaction-assessment"] == FeedbackConfig(enable=True, window_size=5)
    assert loaded.models == {"primary": {"provider": "google", "id": "m"}}


def test_load_keeps_explicit_interaction_assessment(tmp_path):
    """An explicit nested interaction-assessment key survives the roundtrip."""
    path = tmp_path / "semente.yaml"
    manifest = Manifest(
        name="ia",
        features={"interaction-assessment": {"enable": True, "window_size": 10}},
    )
    manifest.save(path)
    loaded = Manifest.load(path)
    assert loaded.features["interaction-assessment"] == FeedbackConfig(enable=True, window_size=10)


def test_load_normalizes_legacy_feedback_keys(tmp_path):
    """Legacy keys merge into `interaction-assessment` (kebab-case convention).

    Legacy keys: `feedback_workflow`, `feedback`, and the branch-intermediate
    `interaction_assessment` snake_case spelling. Precedence: explicit
    kebab-case key > `feedback` (dict) > `feedback_workflow` (bool). Any
    legacy disabled gate disables the feature; only `feedback`/explicit keys
    carry `window_size`.
    """
    # feedback: bool -> config default window_size
    path = tmp_path / "a.yaml"
    path.write_text("name: a\nfeatures:\n  feedback: false\n", encoding="utf-8")
    assert Manifest.load(path).features["interaction-assessment"] == FeedbackConfig(enable=False)

    # feedback: dict carries the window_size; feedback_workflow: true is subsumed
    path = tmp_path / "b.yaml"
    path.write_text(
        "name: b\nfeatures:\n"
        "  feedback_workflow: true\n"
        "  feedback:\n    enable: true\n    window_size: 10\n",
        encoding="utf-8",
    )
    assert Manifest.load(path).features["interaction-assessment"] == FeedbackConfig(enable=True, window_size=10)

    # either legacy disabled gate wins over the other's enable
    path = tmp_path / "c.yaml"
    path.write_text(
        "name: c\nfeatures:\n"
        "  feedback_workflow: false\n"
        "  feedback:\n    enable: true\n",
        encoding="utf-8",
    )
    assert Manifest.load(path).features["interaction-assessment"] == FeedbackConfig(enable=False)

    # an explicit new key wins over the legacy ones entirely
    path = tmp_path / "d.yaml"
    path.write_text(
        "name: d\nfeatures:\n"
        "  interaction-assessment: true\n"
        "  feedback_workflow: false\n",
        encoding="utf-8",
    )
    assert Manifest.load(path).features["interaction-assessment"] == FeedbackConfig(enable=True, window_size=5)
    loaded_keys = set(Manifest.load(path).features)
    assert "feedback_workflow" not in loaded_keys and "feedback" not in loaded_keys

    # the snake_case intermediate spelling also normalizes (with a warning)
    path = tmp_path / "e.yaml"
    path.write_text("name: e\nfeatures:\n  interaction_assessment: true\n", encoding="utf-8")
    assert Manifest.load(path).features["interaction-assessment"] == FeedbackConfig(enable=True, window_size=5)


def test_save_stable_key_order(tmp_path):
    """First keys in the file: name, language, domain_module (readable diffs)."""
    path = tmp_path / "semente.yaml"
    Manifest(name="ordered").save(path)
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if not line.startswith("features:") and not line.startswith("  ") ]
    assert lines[0] == "name: ordered"
    assert lines[1] == "language: en"
    assert lines[2] == "domain_module: domain"


def test_save_omits_unset_optionals(tmp_path):
    """engine=None and models={} are not written (they mean 'use defaults')."""
    path = tmp_path / "semente.yaml"
    Manifest(name="minimal").save(path)
    content = path.read_text(encoding="utf-8")
    assert "engine" not in content
    assert "models" not in content


def test_load_pii_guardrail_alias(tmp_path):
    """The old ``pii_guardrail`` feature key is normalized to ``guardrails``."""
    path = tmp_path / "semente.yaml"
    path.write_text("name: legacy\nfeatures:\n  pii_guardrail: false\n", encoding="utf-8")
    loaded = Manifest.load(path)
    assert loaded.features["guardrails"] is False
    assert "pii_guardrail" not in loaded.features
    # The alias does not survive a save roundtrip (it is normalized away).
    loaded.save(path)
    reloaded = Manifest.load(path)
    assert reloaded.features["guardrails"] is False


def test_load_after_cli_save(tmp_path):
    """A CLI-edited manifest (features dict mutated) still loads."""
    path = tmp_path / "semente.yaml"
    Manifest(name="cli-edit", features={}).save(path)
    m = Manifest.load(path)
    m.features = {**m.features, "tts": False}
    m.save(path)
    reloaded = Manifest.load(path)
    assert reloaded.features["tts"] is False


# ---------------------------------------------------------------------
# features.terms-acceptance
# ---------------------------------------------------------------------
def test_terms_absent_means_off(tmp_path):
    """A domain-neutral default: no key, no terms gate and no injected config."""
    path = tmp_path / "semente.yaml"
    path.write_text("name: no-terms\n", encoding="utf-8")
    loaded = Manifest.load(path)
    assert "terms-acceptance" not in loaded.features


def test_terms_bool_and_mapping_forms(tmp_path):
    path = tmp_path / "a.yaml"
    path.write_text("name: a\nfeatures:\n  terms-acceptance: true\n", encoding="utf-8")
    assert Manifest.load(path).features["terms-acceptance"] == TermsConfig(enable=True)

    path = tmp_path / "b.yaml"
    path.write_text(
        "name: b\nfeatures:\n  terms-acceptance:\n"
        "    enable: true\n    file: domain/terms.md\n    url: https://x.test/t\n",
        encoding="utf-8",
    )
    assert Manifest.load(path).features["terms-acceptance"] == TermsConfig(
        enable=True, file="domain/terms.md", url="https://x.test/t"
    )


def test_terms_snake_case_alias_normalizes(tmp_path):
    path = tmp_path / "semente.yaml"
    path.write_text("name: c\nfeatures:\n  terms_acceptance: true\n", encoding="utf-8")
    loaded = Manifest.load(path)
    assert loaded.features["terms-acceptance"] == TermsConfig(enable=True)
    assert "terms_acceptance" not in loaded.features


def test_terms_roundtrip_and_source_dir(tmp_path):
    path = tmp_path / "nested" / "semente.yaml"
    path.parent.mkdir()
    Manifest(
        name="terms-app",
        features={"terms-acceptance": TermsConfig(enable=True, file="terms.md")},
    ).save(path)

    loaded = Manifest.load(path)
    assert loaded.source_dir == path.parent.resolve()
    assert loaded.features["terms-acceptance"] == TermsConfig(enable=True, file="terms.md")
    assert loaded.to_dict()["features"]["terms-acceptance"] == {
        "enable": True, "file": "terms.md", "url": ""
    }