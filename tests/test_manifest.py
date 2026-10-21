"""Manifest save/load roundtrip and key stability."""

from pathlib import Path

from semente.manifest import Manifest


def test_save_load_roundtrip(tmp_path):
    """What save() writes, load() reads back unchanged.

    ``load()`` injects the ``feedback`` feature default as a ``FeedbackConfig``
    (with ``enable``/``window_size``) — the roundtrip is stable once compared
    through ``to_dict``.
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
    from semente.manifest import FeedbackConfig

    assert loaded.features["feedback"] == FeedbackConfig(enable=True, window_size=5)
    assert loaded.models == {"primary": {"provider": "google", "id": "m"}}


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