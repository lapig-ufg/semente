"""The supervised_run agents — the supervisor that routes, the checkpoint that judges.

Both agents have no tools and do no domain work; both read the step's
knowledge only through the domain's :class:`SupervisedRun` object (the
``get_supervised_run`` seam) rendered into the generic prompt contracts
(``supervised_run_agent`` / ``supervised_run_check_agent`` tags in ``agents.yml``).

The SUPERVISOR (the FIRST agent) rides above the normal agent while the
supervised_run runs: every user message is graded BEFORE the normal agent — its
whole output is a :class:`SupervisedRunDecision` structured answer:

    forward=True    -> the pipeline runs the normal agent with the user's
                       input, so the real assistant behaves exactly as it
                       does outside the supervised_run (registrations,
                       analyses...).
    forward=False   -> the pipeline delivers the supervisor's ``content``
                       instead: the step's lesson or the coaching reply.
    abandon_supervised_run-> the user wants out; the pipeline closes the supervised_run.

The CHECKPOINT (the SECOND agent) runs after a forwarded turn: the current
step's ``complete_condition`` — a str — is judged from the real assistant's
reply over the conversation (:class:`CompletionCheck` structured answer,
fail-closed). A callable condition is executed by the pipeline directly —
the checkpoint is not involved. This module also owns the completion
announcement (the congrats + next lesson / closing the pipeline appends
when a step completes).

Nothing here knows the step count or the step contents: the steps are
whatever the domain returns. ``resolve_supervised_run`` resolves the seam for
:func:`semente.core.semente_agent.get_agent`.
"""

from typing import Any, Optional

from semente.backends.base import AgentSpec
from semente.backends.registry import get_backend
from semente.configs.prompts import get_agent_config
from semente.domain.base import SupervisedRun
from semente.logging import log_debug, log_error, log_warning
from semente.schemas.supervised_run import CompletionCheck, SupervisedRunDecision
from semente.schemas.workflow_state import SUPERVISED_RUN_COMPLETED, parse_supervised_run_state

MANIFEST_FEATURE = "supervised_run"


# =====================================================================
# Shared helpers (seam, position, prompt text fallback)
# =====================================================================


def resolve_supervised_run(domain_spec, manifest) -> Optional[SupervisedRun]:
    """Resolve the domain's supervised_run spec (``None`` = the feature is off).

    The supervised_run exists when the domain supplies ``get_supervised_run`` returning a
    :class:`SupervisedRun` with steps — unless ``features.supervised_run`` is false in
    the manifest. Any misconfiguration (getter failing, no steps) disables
    the feature with a warning instead of crashing the build.
    """
    getter = getattr(domain_spec, "get_supervised_run", None)
    if getter is None:
        return None

    features = getattr(manifest, "features", None) or {}
    if not features.get(MANIFEST_FEATURE, True):
        log_debug("resolve_supervised_run: features.supervised_run=false — feature off")
        return None

    try:
        supervised_run = getter()
    except Exception as exc:
        log_error(f"resolve_supervised_run: get_supervised_run() failed; supervised_run disabled: {exc}")
        return None

    if supervised_run is None or not getattr(supervised_run, "steps", None):
        log_warning(
            "resolve_supervised_run: get_supervised_run returned no steps; supervised_run disabled — "
            "pass get_supervised_run=None to drop the feature cleanly"
        )
        return None
    return supervised_run


def current_step_index(supervised_run: SupervisedRun, workflow_state: dict) -> int:
    """The 0-based index of the step in flight (defensively clamped).

    ``None``/junk state grades as step 0; an out-of-range persisted index
    (the SupervisedRun changed between the session being saved and now) clamps to
    the last step.
    """
    parsed = parse_supervised_run_state(workflow_state.get("supervised_run_state"))
    index = int(parsed) if parsed and parsed != SUPERVISED_RUN_COMPLETED else 0
    return min(max(index, 0), len(supervised_run.steps) - 1)


def _text(supervised_run_config: dict, key: str, fallback: str) -> str:
    """One prompt text with an inline fallback (a missing key can never crash a run)."""
    value = supervised_run_config.get(key)
    if not isinstance(value, str) or not value.strip():
        return fallback
    return value.strip()


def build_geo_attachment_note() -> str:
    """Text appended to the supervisor's input when the run has geo files.

    The supervisor is text-only: to judge a "send a file" step it must see
    that the converted GeoJSON attachment exists. The wording comes from
    ``agents.yml`` (``supervised_run_agent.geo_attachment_note``) so each app can
    localize it; a missing key falls back to a generic English note.
    """
    return _text(
        get_agent_config("supervised_run_agent"),
        "geo_attachment_note",
        "the user attached a geospatial file (converted to GeoJSON)",
    )


# =====================================================================
# SUPERVISOR — the first agent: routes every message (forward/lesson)
# =====================================================================


def _step_section(step, index: int, total: int) -> str:
    """Renders one step's prompt section from the domain's SupervisedRunStep."""
    return "\n".join(
        [
            f"# CURRENT STEP — Step {index + 1} of {total} (id: {step.id})",
            "## Lesson (when `lesson_delivered: no`)",
            "Do NOT evaluate the path and DO NOT forward: your `content` is "
            "this step's lesson, in one short chat-style message:",
            step.lesson.strip(),
            "## Forward when (`forward=true`, empty content)",
            step.forward_condition.strip(),
        ]
    )


def supervised_run_instructions(run_context, supervised_run: SupervisedRun) -> str:
    """Builds the supervisor's instructions for the current supervised_run step.

    The generic contract (the ``supervised_run_agent.instructions`` template in
    ``agents.yml``) is formatted with: the ``<supervised_run_state>`` dynamic block
    (current step, whether the lesson was delivered, history context), the
    current step's section (lesson + forward condition from the domain's
    ``SupervisedRunStep``) and the leave-early text (``SupervisedRun.abandon``, a yml
    default when absent). Called by the backend every run; exposed at module
    level so tests can assert the composition directly.
    """
    supervised_run_config = get_agent_config("supervised_run_agent")

    session_state = run_context.session_state or {}
    workflow_state = session_state.get("workflow_state") or {}
    lesson_delivered = "yes" if workflow_state.get("supervised_run_intro_sent") else "no"
    history_context = session_state.get("history_context") or ""

    steps = supervised_run.steps
    total = len(steps)
    index = current_step_index(supervised_run, workflow_state)
    step = steps[index]

    dynamic_block = "\n".join(
        [
            f"supervised_run_progress: {index + 1}/{total} (id: {step.id})",
            f"lesson_delivered: {lesson_delivered}",
            f"<history_context>{history_context}</history_context>",
        ]
    )

    abandon_text = (
        supervised_run.abandon.strip()
        if supervised_run.abandon and supervised_run.abandon.strip()
        else _text(
            supervised_run_config,
            "abandon_default",
            "A graceful closing: no pressure — the user can keep using the "
            "system normally and is welcome back whenever they want.",
        )
    )

    template = (supervised_run_config.get("instructions") or "").strip()
    return template.format(
        step_instructions=_step_section(step, index, total),
        abandon_text=abandon_text,
        supervised_run_state=dynamic_block,
    )


def build_supervised_run_agent(supervised_run: SupervisedRun):
    """Build the supervised_run supervisor for the given ``SupervisedRun`` spec.

    Prompts are read per run by :func:`supervised_run_instructions` (so the
    prompts dir can be re-pointed); the ``SupervisedRun`` object is closed over by
    the instructions callable. Never called with a falsy supervised_run — the
    pipeline resolves the spec first (:func:`resolve_supervised_run`) and simply
    wires no supervisor when the feature is off.
    """
    supervised_run_config = get_agent_config("supervised_run_agent")

    spec = AgentSpec(
        name=supervised_run_config["name"],
        instructions=lambda run_context: supervised_run_instructions(run_context, supervised_run),
        output_schema=SupervisedRunDecision,
    )
    return get_backend().build_agent(spec)


# =====================================================================
# CHECKPOINT — the second agent: judges step completion after a forward
# =====================================================================

COMPLETION_PAYLOAD = (
    "<user_message>\n{user_message}\n</user_message>\n\n"
    "<assistant_reply>\n{agent_reply}\n</assistant_reply>"
)


def completion_payload(user_text: str, agent_reply: str) -> str:
    """The text the pipeline sends to the checkpoint: the turn being judged."""
    return COMPLETION_PAYLOAD.format(
        user_message=(user_text or "").strip(),
        agent_reply=(agent_reply or "").strip(),
    )


def supervised_run_check_instructions(run_context, supervised_run: SupervisedRun) -> str:
    """Builds the checkpoint agent's instructions for the current step.

    The generic contract (the ``supervised_run_check_agent.instructions`` template
    in ``agents.yml``) is formatted with the current step's completion
    condition (a ``str`` — callables never reach this agent) and the
    ``<supervised_run_state>`` dynamic block (progress + history context). The
    user's message and the assistant's reply arrive as the run's input text,
    NOT here. Called by the backend every run; exposed at module level so
    tests can assert the composition directly.
    """
    check_config = get_agent_config("supervised_run_check_agent")
    fallback_template = (
        "# Who You Are\n"
        "You are the SupervisedRun Checkpoint. Decide whether the step's completion "
        "condition below was plainly met by the conversation — answer ONLY with "
        "the structured decision."
    )

    session_state = run_context.session_state or {}
    workflow_state = session_state.get("workflow_state") or {}
    history_context = session_state.get("history_context") or ""

    steps = supervised_run.steps
    total = len(steps)
    index = current_step_index(supervised_run, workflow_state)
    condition = steps[index].complete_condition

    dynamic_block = "\n".join(
        [
            f"current_step: {steps[index].id} ({index + 1}/{total})",
            f"<history_context>{history_context}</history_context>",
            "<completion_condition>",
            str(condition),
            "</completion_condition>",
        ]
    )

    template = (check_config.get("instructions") or "").strip() or fallback_template
    return template.format(supervised_run_state=dynamic_block, complete_condition=str(condition))


def build_completion_announcement(supervised_run: SupervisedRun, state: dict) -> Optional[str]:
    """The text appended to the reply when the current step just completed.

    With a next step: the framework congrats template with the next step's
    lesson embedded (the user hears "congrats" and the next teaching in the
    same breath). On the last step: the supervised_run's closing (the domain's
    override or the generic default in ``agents.yml``).
    """
    workflow_state = state.get("workflow_state") or {}
    index = current_step_index(supervised_run, workflow_state)
    step = supervised_run.steps[index]

    next_step = supervised_run.steps[index + 1] if index + 1 < len(supervised_run.steps) else None

    if next_step is None:
        if supervised_run.closing and supervised_run.closing.strip():
            return supervised_run.closing.strip()
        config = get_agent_config("supervised_run_agent")
        return _text(
            config,
            "closing_default",
            "Congratulate the user for finishing ALL the steps and remind "
            "them they can now use the system freely, whenever they want.",
        )

    check_config = get_agent_config("supervised_run_check_agent")
    template = _text(
        check_config,
        "completion_announcement",
        'The "{step_id}" step is complete! Let us move to the next one:\n{next_lesson}',
    )
    next_lesson = next_step.lesson.strip()
    return template.format(step_id=step.id, next_lesson=next_lesson)


def build_supervised_run_check_agent(supervised_run: SupervisedRun):
    """Build the supervised_run checkpoint for the given ``SupervisedRun`` spec.

    Prompts are read per run by :func:`supervised_run_check_instructions`; the
    ``SupervisedRun`` object is closed over by the instructions callable. Only
    meaningful for steps whose ``complete_condition`` is a ``str``; the
    pipeline simply never runs it for callable conditions.
    """
    check_config = get_agent_config("supervised_run_check_agent")

    spec = AgentSpec(
        name=check_config["name"],
        instructions=lambda run_context: supervised_run_check_instructions(run_context, supervised_run),
        output_schema=CompletionCheck,
    )
    return get_backend().build_agent(spec)


def parse_completion_check(turn: Any) -> bool:
    """The checkpoint's ``step_completed`` verdict (fail-closed: anything off is False)."""
    if turn is None or not turn.structured:
        return False
    try:
        check = CompletionCheck.model_validate(turn.structured)
    except Exception:
        return False
    return check.step_completed