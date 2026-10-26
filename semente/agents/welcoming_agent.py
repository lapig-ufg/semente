from enum import Enum, auto
from pathlib import Path
from typing import Any, Dict, List

from semente.backends.base import AgentSpec
from semente.backends.registry import get_backend
from semente.configs.prompts import get_agent_config
from semente.manifest import TermsConfig
from semente.schemas.user_persona import (
    is_persona_complete,
    is_persona_field_informed,
)


class OnboardingStatus(Enum):
    NOT_ACCEPTED_TERMS = auto()
    NOT_INFORMED_PERSONA = auto()
    COMPLETE = auto()


def _normalize_terms(terms) -> TermsConfig:
    """Accept ``None``/bool/dict/TermsConfig (programmatic manifests)."""
    if isinstance(terms, TermsConfig):
        return terms
    if isinstance(terms, dict):
        return TermsConfig(**terms)
    if terms is None:
        return TermsConfig()
    return TermsConfig(enable=bool(terms))


def _load_terms_text(config: TermsConfig, base_dir: Path | None) -> str:
    """Read the reference terms text, failing loudly on a misconfiguration.

    A terms gate without the actual terms would record consent the user could
    never have read, so a missing file is a startup error, not a warning.
    """
    if not config.file:
        raise ValueError(
            "features.terms-acceptance is enabled but has no 'file' configured; "
            "point it at the reference terms text (e.g. domain/terms.md)."
        )

    path = Path(config.file).expanduser()
    if not path.is_absolute():
        path = Path(base_dir or Path.cwd()) / path

    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise FileNotFoundError(
            f"features.terms-acceptance.file not found or unreadable: {path}"
        ) from exc


def _get_onboarding_status(
    session_state: Dict[str, Any], terms_enabled: bool = True
) -> OnboardingStatus:
    """Decide which onboarding stage the user is currently on.

    Reads ``terms_accepted`` and ``user_persona`` (a plain dict) from the
    session state and drives both the instructions and the toolset: the terms
    prompt/tool only while the terms are pending and the gate is enabled, the
    persona prompt/tools only while name or role are missing. Completeness is
    judged with the shared ``is_persona_complete`` rule, so it can never drift
    from the workflow gate.
    """
    if terms_enabled and not session_state.get("terms_accepted", False):
        return OnboardingStatus.NOT_ACCEPTED_TERMS

    if not is_persona_complete(session_state.get("user_persona")):
        return OnboardingStatus.NOT_INFORMED_PERSONA

    return OnboardingStatus.COMPLETE


def build_welcoming_agent(
    tts_enabled: bool = True,
    terms=None,
    app_name: str = "this assistant",
    base_dir: Path | None = None,
):
    """Build the staged welcoming agent via the selected engine backend.

    One stage per prompt: the terms stage (``instructions`` +
    ``accept_terms_and_conditions``, only when ``features.terms-acceptance``
    is enabled) and the persona stage (``instructions_persona`` + name/role
    tools). Only the current stage's tools are exposed (TTS always, when
    enabled). Prompts are loaded lazily so the language/prompts dir can be set
    before this is called; the loaded values are closed over by the callables
    below.

    Args:
        tts_enabled: Attach the TTS tool on every stage.
        terms: The manifest's ``features.terms-acceptance`` value
            (TermsConfig/bool/dict/None). Absent means the terms stage is off.
        app_name: The manifest app name, formatted into the prompts.
        base_dir: Directory used to resolve a relative ``terms.file``.
    """
    welcoming_config = get_agent_config("welcoming_agent")

    terms_config = _normalize_terms(terms)
    terms_enabled = terms_config.enable
    terms_text = _load_terms_text(terms_config, base_dir) if terms_enabled else ""

    if terms_enabled and terms_config.url:
        terms_link_instruction = (
            "In your FIRST message, include this Terms of Use link verbatim: "
            f"{terms_config.url}"
        )
    else:
        terms_link_instruction = (
            "This app has no public Terms of Use link — briefly explain the "
            "terms below and ask for consent in your first message."
        )

    terms_instruction = welcoming_config["instructions"].strip().format(
        app_name=app_name,
        terms_link_instruction=terms_link_instruction,
        terms_text=terms_text,
    )
    persona_instruction = welcoming_config["instructions_persona"].strip()
    persona_not_informed = welcoming_config["persona_not_informed"].strip()

    if terms_enabled:
        terms_closed_note = (
            "The Terms of Use have already been accepted — NEVER resend the "
            "link, repeat the text or ask for acceptance again."
        )
    else:
        terms_closed_note = (
            "This is your first contact with the user: welcome them briefly "
            "and explain what this app does."
        )

    def _get_tools(run_context) -> List:
        session_state = run_context.session_state or {}
        onboarding_status = _get_onboarding_status(
            session_state=session_state, terms_enabled=terms_enabled
        )

        tools: list = []
        if tts_enabled:
            from semente.tools.tts_tools import generate_speech

            tools.append(generate_speech)

        if terms_enabled and onboarding_status == OnboardingStatus.NOT_ACCEPTED_TERMS:
            from semente.tools.onboarding_tools import accept_terms_and_conditions

            tools.append(accept_terms_and_conditions)

        if onboarding_status == OnboardingStatus.NOT_INFORMED_PERSONA:
            from semente.tools.persona_tools import (
                update_persona_name,
                update_persona_role,
            )

            tools.extend([update_persona_name, update_persona_role])

        return tools

    def get_instructions(run_context) -> str:
        session_state = run_context.session_state or {}
        onboarding_status = _get_onboarding_status(
            session_state=session_state, terms_enabled=terms_enabled
        )

        if onboarding_status == OnboardingStatus.NOT_ACCEPTED_TERMS:
            return terms_instruction

        if onboarding_status == OnboardingStatus.NOT_INFORMED_PERSONA:
            user_persona = session_state.get("user_persona") or {}

            user_name = user_persona.get("name")
            user_role = user_persona.get("role")

            if not is_persona_field_informed(user_name):
                user_name = persona_not_informed
            if not is_persona_field_informed(user_role):
                user_role = persona_not_informed

            return persona_instruction.format(
                app_name=app_name,
                terms_closed_note=terms_closed_note,
                user_name=user_name,
                user_role=user_role,
            )

        # Onboarding complete: the workflow gate routes these users away from
        # the welcoming agent, so there is no instruction to give.
        return ""

    spec = AgentSpec(
        name=welcoming_config["name"],
        instructions=get_instructions,
        tools=_get_tools,
    )
    return get_backend().build_agent(spec)
