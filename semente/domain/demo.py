"""The demo domain — a clean, tools-less DomainSpec for ``--demo`` runs.

Used by ``semente launch streamlit --demo`` when the user has no app yet: the agent
boots with the bundled default prompts and the generic instruction builder,
proving the framework end-to-end without any domain code or manifest.
"""

from __future__ import annotations

from semente.domain.base import DomainSpec


def demo_domain_spec() -> DomainSpec:
    """A minimal clean-start domain: no tools, no knowledge, no skills."""
    return DomainSpec(name="Semente Demo")