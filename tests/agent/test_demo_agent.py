"""Demo mode: SEMENTE_DEMO=1 builds the agent from built-in defaults.

Regression: ``semente launch streamlit --demo`` must boot in a directory with no
semente.yaml and no domain package — the built-in manifest + demo_domain_spec
replace both.
"""

from pathlib import Path


def test_get_agent_demo_mode(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)  # no semente.yaml, no domain/ here
    monkeypatch.setenv("SEMENTE_DEMO", "1")
    monkeypatch.setenv("GOOGLE_API_KEY", "dummy-test-key")

    import semente.core.semente_agent as sa

    monkeypatch.setattr(sa, "_agent_cache", None)
    agent = sa.get_agent()

    assert agent.name == "semente-demo"

    # No domain module was imported from the test dir (there is none).
    import sys

    assert "domain" not in sys.modules


def test_get_agent_demo_mode_ignores_manifest_arg(monkeypatch, tmp_path):
    """SEMENTE_DEMO=1 wins even when get_agent receives a manifest path."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SEMENTE_DEMO", "1")
    monkeypatch.setenv("GOOGLE_API_KEY", "dummy-test-key")

    import semente.core.semente_agent as sa

    monkeypatch.setattr(sa, "_agent_cache", None)
    agent = sa.get_agent(manifest_path="nonexistent-semente.yaml")

    assert agent.name == "semente-demo"


def test_demo_domain_spec_is_clean():
    """The demo spec: no tools, no knowledge, no skills — a clean start."""
    from semente.domain import demo_domain_spec

    spec = demo_domain_spec()
    assert spec.name == "Semente Demo"
    assert spec.tools == []
    assert spec.knowledge is None
    assert spec.skills is None
    assert spec.agent_config == "single_agent"