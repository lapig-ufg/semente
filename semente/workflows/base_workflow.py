"""Base workflow composition — the neutral orchestration engine.

Assembles the root workflow: onboarding check (terms acceptance +
identification profile) → parallel feedback/summarization + the single
agent → remediation merge → output.

Feature toggles (manifest ``features``) control which steps are included:
``pii_guardrail``, ``summarization``, ``feedback_workflow``, ``tts``.

``build_workflow(agent, manifest)`` builds the workflow for a given agent;
``get_workflow()`` loads the manifest + domain, applies the language prompts
dir, builds the agent, and returns a cached workflow singleton.

Prompt-loading modules (steps, agents, feedback workflow) are imported lazily
inside ``build_workflow`` so the language/prompts dir can be set first.
"""

import importlib
import os
from pathlib import Path
from typing import Any

from semente.agents.build_agent import build_agent
from semente.configs.config import config
from semente.configs.prompts import set_prompts_dir
from semente.core.orchestrator import Condition, Parallel, Step, Workflow
from semente.core.step_factory import agent_executor_factory
from semente.database.session_store import store
from semente.domain import DomainSpec
from semente.manifest import Manifest
from semente.workflows.onboarding_gate import _needs_onboarding


def build_workflow(agent: Any, manifest: Manifest) -> Workflow:
    """Assemble the root workflow for a built agent, honoring feature toggles."""
    # Deferred imports — these modules load prompts at import time, so they
    # must be imported after the language/prompts dir has been applied.
    from semente.agents.welcoming_agent import build_welcoming_agent
    from semente.steps.feedback.remediation import (
        INTENT_ROUTER_STEP_NAME,
        remediation_check_step,
    )
    from semente.steps.guardrails_step import guardrails_step
    from semente.steps.input_step import input_step
    from semente.steps.output_step import output_step
    from semente.steps.summarization_step import summarization_step
    from semente.workflows.feedback_workflow import feedback_workflow

    features = manifest.features or {}

    steps: list[Any] = [input_step]
    if features.get("pii_guardrail", True):
        steps.append(guardrails_step)

    # Parallel branch: summarization + feedback (optional) + the single agent.
    parallel_steps: list[Any] = []
    if features.get("summarization", True):
        parallel_steps.append(summarization_step)
    if features.get("feedback_workflow", True):
        parallel_steps.append(feedback_workflow)
    parallel_steps.append(
        Step(
            name=INTENT_ROUTER_STEP_NAME,
            executor=agent_executor_factory(agent=agent, include_summary=True),
        )
    )

    welcoming_agent = build_welcoming_agent(tts_enabled=features.get("tts", True))

    steps.append(
        Condition(
            name="Onboarding Check",
            evaluator=_needs_onboarding,
            steps=[
                Step(
                    name="Welcoming Agent",
                    executor=agent_executor_factory(welcoming_agent, include_summary=False),
                ),
            ],
            else_steps=[
                Parallel(*parallel_steps, name="Feedback and Routing"),
                remediation_check_step,
            ],
        )
    )
    steps.append(output_step)

    return Workflow(
        name=f"{manifest.name} Workflow",
        steps=steps,
        store=store,
    )


def _load_domain(manifest: Manifest) -> DomainSpec:
    """Import the app's domain module and return its ``domain_spec``.

    The app's cwd is added to ``sys.path`` so the domain package (which lives
    next to ``semente.yaml``) is importable regardless of how the app is run.
    """
    import sys

    cwd = str(Path.cwd())
    if cwd not in sys.path:
        sys.path.insert(0, cwd)

    module = importlib.import_module(manifest.domain_module)
    spec = getattr(module, "domain_spec", None)
    if spec is None:
        raise AttributeError(
            f"Domain module '{manifest.domain_module}' must expose a 'domain_spec' "
            "(a semente.domain.DomainSpec instance)."
        )
    return spec


def _apply_prompts(manifest: Manifest) -> None:
    """Point the prompts loader at the app's prompts dir.

    Priority: explicit ``prompts_dir``, then ``prompts/<language>/`` if it exists.
    """
    if manifest.prompts_dir:
        set_prompts_dir(Path.cwd() / manifest.prompts_dir)
    elif manifest.language and manifest.language.lower() != "en":
        lang_dir = Path.cwd() / "prompts" / manifest.language
        if lang_dir.exists():
            set_prompts_dir(lang_dir)


_workflow_cache: Workflow | None = None


def get_workflow(manifest_path: str | None = None) -> Workflow:
    """Load manifest + domain, apply language, build the agent and workflow, cache."""
    global _workflow_cache
    if _workflow_cache is not None:
        return _workflow_cache

    path = manifest_path or os.getenv("SEMENTE_MANIFEST", "semente.yaml")
    manifest = Manifest.load(path)
    # Pin the engine BEFORE any sub-agent module is imported (they call
    # get_backend() at import time and must resolve to the manifest's engine).
    from semente.backends.registry import set_engine

    set_engine(manifest.engine)
    _apply_prompts(manifest)
    domain_spec = _load_domain(manifest)
    agent = build_agent(domain_spec, manifest)
    _workflow_cache = build_workflow(agent, manifest)
    return _workflow_cache
