"""Semente — the single-object pipeline that replaces the workflow engine.

One object owns the whole conversation turn: ``run()`` is a thin sequencer
and each unique stage of the old workflow is a private method whose return
value is passed explicitly to the next call (no ``StepInput`` thread-local
registry, no step-name lookups).

Pipeline (feature toggles from the manifest ``features`` in parentheses):

    _input_preprocessing   media -> text, geo files -> GeoJSON (always)
    _redact_pii            PII markers on the consolidated text (pii_guardrail)
    _needs_onboarding      terms + profile gate (always)
    ├─ True:  _run_welcoming_agent
    └─ False: _summarize_conversation (summarization)
              _process_feedback      (feedback_workflow)
              _run_single_agent      (always; sees summary + history)
              _apply_remediation    (part of the feedback loop)
    _finalize_output       audio transcript -> synthesized voice (tts)
    _persist_session       state + history back to the store

Media/summary/feedback/persona agents are imported lazily *inside* the
methods: their modules build agents at import time, so they must only be
imported after the language/prompts dir has been applied (``get_agent``).

External interface:
    Semente      -- the agent object the channels call.
    get_agent     -- manifest + domain + prompts loading, cached singleton.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any, Optional

from semente.backends.base import AgentInput
from semente.configs.prompts import set_prompts_dir
from semente.core.types import AgentSession, SessionStore, StepOutput
from semente.logging import log_debug, log_error, log_info
from semente.manifest import Manifest
from semente.schemas.input_manager import InputManager
from semente.schemas.user_mood import UserMood
from semente.schemas.user_persona import (
    is_persona_complete,
    is_persona_field_informed,
)
from semente.schemas.workflow_state import WorkflowState
from semente.services.session_migration import migrate_session_state
from semente.tools.types import File

# ---------------------------------------------------------------------------
# Geo intake helpers
# ---------------------------------------------------------------------------

SUMMARY_THRESHOLD = 6
HISTORY_WINDOW = 4

# Default fallback satisfaction level when the evaluation agent fails.
_DEFAULT_SATISFACTION = {"level": 3, "level_message": "Neutral (default)"}


def _file_name(file: File) -> str:
    """Resolves the filename of a Semente ``File`` (name, filename or filepath)."""
    name = file.name or file.filename
    if name:
        return str(name)
    if file.filepath:
        return Path(str(file.filepath)).name
    return ""


def _file_content(file: File) -> bytes:
    """Resolves the content of a Semente ``File`` (inline bytes or filepath)."""
    if file.content:
        return file.content
    if file.filepath:
        try:
            return Path(file.filepath).read_bytes()
        except OSError as error:
            log_error(f"could not read file {file.filepath}: {error}")
    return b""


def _convert_geo_files(files: list[File]) -> tuple[list[File], list[str]]:
    """Converts supported geospatial files to GeoJSON ``File`` objects.

    Returns:
        Tuple (converted files, error notices).
    """
    from semente.services.geospatial.geojson_io import (
        SUPPORTED_EXTENSIONS,
        GeoFileError,
        UnsupportedFormatError,
        convert_geo_file_to_geojson,
        save_debug_json,
    )

    converted: list[File] = []
    errors: list[str] = []

    for file in files:
        filename = _file_name(file)
        content = _file_content(file)
        if not content:
            continue

        if Path(filename).suffix.lower() not in SUPPORTED_EXTENSIONS:
            # WhatsApp may omit the filename; sniff the file type from its
            # magic bytes. Files that are not geospatial are left untouched.
            from semente.services.geospatial.geojson_io import resolve_geo_filename

            resolved = resolve_geo_filename(filename, content)
            if Path(resolved).suffix.lower() in SUPPORTED_EXTENSIONS:
                filename = resolved
            else:
                continue

        try:
            geojson_bytes = convert_geo_file_to_geojson(content, filename)
        except UnsupportedFormatError:
            continue
        except GeoFileError as error:
            log_error(f"geojson conversion failed for {filename}: {error}")
            errors.append(str(error))
            continue
        except Exception as error:  # pragma: no cover - defensive
            log_error(f"unexpected geojson conversion failure for {filename}: {error}")
            errors.append(
                "Ocorreu um erro inesperado ao processar o arquivo enviado. "
                "Tente novamente com outro arquivo."
            )
            continue

        stem = Path(filename).stem or "property"
        debug_path = save_debug_json(geojson_bytes, f"input_converted_{stem}")
        if debug_path:
            log_debug(f"converted geojson saved for debugging: {debug_path}")

        converted.append(
            File(
                content=geojson_bytes,
                mime_type="application/json",
                name=f"{stem}.json",
                format="geojson",
            )
        )

    return converted, errors


# ---------------------------------------------------------------------------
# Semente
# ---------------------------------------------------------------------------

class Semente:
    """The whole conversation pipeline as a single object.

    Args:
        agent: The single backend agent built from the DomainSpec.
        welcoming_agent: The onboarding agent (terms + persona stages).
        manifest: The parsed ``semente.yaml`` — name and feature toggles.
        store: Optional :class:`SessionStore` for cross-run persistence.
    """

    def __init__(
        self,
        agent: Any,
        welcoming_agent: Any,
        manifest: Manifest,
        store: Optional[SessionStore] = None,
    ):
        self.agent = agent
        self.welcoming_agent = welcoming_agent
        self.name = manifest.name
        self.features = manifest.features or {}
        self.store = store

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    def run(
        self,
        *,
        user_id: str,
        session_id: str,
        input: Any = None,
        images: Optional[list] = None,
        videos: Optional[list] = None,
        audio: Optional[list] = None,
        files: Optional[list] = None,
        session_state: Optional[dict] = None,
        stream: bool = False,
    ) -> StepOutput:
        """Run one full conversation turn.

        Args:
            user_id / session_id: Persistence coordinates.
            input: Raw user input (text or JSON-serializable value).
            images/videos/audio/files: Semente media objects.
            session_state: Initial state (used only when the store has none).
            stream: Kept for interface compatibility; runs synchronously.

        Returns:
            The final :class:`StepOutput` (content, media, metrics).
        """
        if stream:
            log_debug("Semente.run(stream=True): running synchronously.")

        session = self._load_session(user_id, session_id, session_state)
        state = session.session_state

        user_text, geo_files = self._input_preprocessing(input, images, audio, files)

        if self.features.get("pii_guardrail", True):
            user_text = self._redact_pii(user_text)

        if self._needs_onboarding(state, user_id):
            final = self._run_welcoming_agent(session, user_text, images, audio)
        else:
            if self.features.get("summarization", True):
                self._summarize_conversation(session, user_text, state)
            if self.features.get("feedback_workflow", True):
                self._process_feedback(session, user_text, state)
            agent_input = self._build_agent_input(session, user_text, state)
            routed = self._run_single_agent(agent_input, images, audio, geo_files, state, user_id)
            final = self._apply_remediation(routed, state)

        final = self._finalize_output(final, user_id)
        self._persist_session(session, input, final)
        return final

    def get_session_state(self, user_id: Optional[str] = None, session_id: str = "") -> dict:
        """Load the persisted session state (used by the debug panel)."""
        if self.store is not None:
            loaded = self.store.get(user_id, session_id)
            if loaded is not None:
                return loaded.get("session_state", {})
        return {}

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def _load_session(
        self, user_id: str, session_id: str, session_state: Optional[dict]
    ) -> AgentSession:
        """Load the (store-backed) session, or start a fresh one."""
        if self.store is not None:
            loaded = self.store.get(user_id, session_id)
            if loaded is not None:
                return AgentSession(
                    user_id=user_id,
                    session_id=session_id,
                    session_state=loaded.get("session_state", {}),
                    runs=loaded.get("runs", []),
                )
        return AgentSession(
            user_id=user_id,
            session_id=session_id,
            session_state=session_state or {},
        )

    def _persist_session(self, session: AgentSession, user_input: Any, final: StepOutput) -> None:
        """Save the session state and append the run to the history."""
        if self.store is None:
            return
        user_text = user_input if isinstance(user_input, str) else str(user_input or "")
        session.runs.append({"user": user_text, "assistant": final.content or ""})
        self.store.save(
            session.user_id,
            session.session_id,
            session_state=session.session_state,
            runs=session.runs,
        )

    # ------------------------------------------------------------------
    # Input pre-processing
    # ------------------------------------------------------------------

    def _input_preprocessing(
        self,
        input: Any,
        images: Optional[list],
        audio: Optional[list],
        files: Optional[list],
    ) -> tuple[str, Optional[list[File]]]:
        """Convert media to text and geospatial documents to GeoJSON.

        Returns:
            Tuple ``(user_text, geo_files)`` — the consolidated text for the
            next stages and the converted GeoJSON files for the agent.

        The transcription and the description are redacted HERE, and not in
        the PII guardrail: the redacted text is what gets persisted in the
        run history, so redacting one stage later would leave a raw copy in
        the database. Typed text arrives already redacted (MessageContent
        __post_init__ in whatsapp/helpers; streamlit_webapp).
        """
        from semente.guardrails.pii_gate import redigir_pii

        parts: list[str] = []

        texto = _input_as_string(input)
        if texto:
            parts.append(texto)

        if images:
            from semente.agents.media_agents import image_description_agent

            try:
                turn = image_description_agent.run(AgentInput(text="", images=images))
                # Redigida AQUI, e não no guardrail: a transcrição/descrição
                # é o que fica gravado no histórico da run, que é persistido.
                # Redigir só no estágio seguinte deixaria uma cópia crua no banco.
                description, _ = redigir_pii(turn.content or "")
                log_debug(f"Image description: {description}")
                if description:
                    parts.append(f"[IMAGEM]{description}[/IMAGEM]")
            except Exception as e:
                log_error(f"image description failed: {e}")

        if audio:
            from semente.agents.media_agents import audio_transcription_agent

            try:
                turn = audio_transcription_agent.run(AgentInput(text="", audio=audio))
                # Mesma razão da descrição da imagem: redige antes de persistir.
                transcription, _ = redigir_pii(turn.content or "")
                log_debug(f"Audio transcription: {transcription}")
                if transcription:
                    parts.append(transcription)
            except Exception as e:
                log_error(f"audio transcription failed: {e}")

        geo_files: Optional[list[File]] = None
        if files:
            from semente.services.geospatial.geojson_io import geopandas_import_available

            if geopandas_import_available():
                log_debug("Converting geo file to GeoJson...")
                converted, errors = _convert_geo_files(files)
                geo_files = converted or None
            else:
                log_error(
                    "geo files received but the 'geo' extra is not installed "
                    "(geopandas/shapely); files ignored"
                )
                errors = []
            for error in errors:
                parts.append(
                    f"[ARQUIVO GEOESPACIAL]Não foi possível processar o arquivo enviado: "
                    f"{error}[/ARQUIVO GEOESPACIAL]"
                )

        return "\n".join(parts), geo_files

    # ------------------------------------------------------------------
    # PII guardrail
    # ------------------------------------------------------------------

    def _redact_pii(self, user_text: str) -> str:
        """Redact personal data from the consolidated text.

        The user keeps the requests they made in the same message, and the
        datum never reaches the agent. Typed text is already redacted at the
        entry doors; this covers what only became text inside this turn
        (audio transcription, image description).
        """
        from semente.guardrails.pii_gate import redigir_pii

        text = user_text if isinstance(user_text, str) else str(user_text)
        limpo, tipos = redigir_pii(text)
        if tipos:
            # Only the types, never the values.
            log_info(f"guardrail PII: dados removidos ({', '.join(tipos)})")
        return limpo

    # ------------------------------------------------------------------
    # Onboarding gate
    # ------------------------------------------------------------------

    def _needs_onboarding(self, state: dict, user_id: Optional[str]) -> bool:
        """Return True if the user still needs to go through onboarding.

        Onboarding covers the formal acceptance of the terms and the
        identification profile (name + role). Both are resolved from
        ``session_state`` when present and only looked up in the database
        for the parts still missing, so a user who already completed them
        is never asked again — not even in a brand new session. On the way
        out, the stored profile is copied into ``session_state`` so the
        agent can personalise from the first reply.

        The completeness rule (``is_persona_complete``) is shared with the
        welcoming agent, so the gate and the agent can never disagree on
        whether the user's identification is done.
        """
        from semente.database.models import UserProfile, UserTermsAcceptance
        from semente.database.session import SessionLocal

        migrated_state = migrate_session_state(state)
        state.clear()
        state.update(migrated_state)

        if state.get("workflow_state") is None:
            state["workflow_state"] = WorkflowState().model_dump()

        terms_accepted = bool(state.get("terms_accepted"))
        persona = state.get("user_persona") or {}

        if terms_accepted and is_persona_complete(persona):
            return False

        user_id = user_id or state.get("user_id")
        if not user_id:
            return True

        db_session = SessionLocal()
        try:
            if not terms_accepted:
                aceite = db_session.query(UserTermsAcceptance).filter(
                    UserTermsAcceptance.user_id == user_id,
                    UserTermsAcceptance.accepted == True,  # noqa: E712
                ).first()

                if not aceite:
                    return True

                state["terms_accepted"] = True

            if not is_persona_complete(persona):
                perfil = db_session.query(UserProfile).filter(
                    UserProfile.user_id == user_id
                ).first()

                if perfil is None:
                    return True

                # Fill only the fields still missing (or still holding the
                # schema sentinel), preserving values the agent just wrote
                # this session.
                for field in ("name", "role"):
                    if not is_persona_field_informed(persona.get(field)) and getattr(perfil, field):
                        persona[field] = getattr(perfil, field)

                state["user_persona"] = persona

            return not is_persona_complete(state.get("user_persona") or {})
        finally:
            db_session.close()

    # ------------------------------------------------------------------
    # Agent stages
    # ------------------------------------------------------------------

    def _run_welcoming_agent(
        self,
        session: AgentSession,
        user_text: str,
        images: Optional[list],
        audio: Optional[list],
    ) -> StepOutput:
        """Run the staged welcoming agent (terms, then persona)."""
        return self._invoke_agent(
            self.welcoming_agent,
            self._build_agent_input(session, user_text, session.session_state),
            images,
            audio,
            files=None,
            state=session.session_state,
            user_id=session.user_id,
        )

    def _summarize_conversation(
        self, session: AgentSession, user_text: str, state: dict
    ) -> None:
        """Maintain the rolling conversation summary in session state.

        Runs only every ``SUMMARY_THRESHOLD`` turns to avoid recomputing
        each time. Exposes the summary under ``state['conversation_summary']``
        so the agent's dynamic instructions can read it.
        """
        from semente.agents.summary_agent import summary_agent

        summary_state = InputManager.model_validate(state.get("summary_state", {}))

        if summary_state.runs_count < SUMMARY_THRESHOLD:
            summary_state.runs_count += 1
            state["summary_state"] = summary_state.model_dump()
            state["conversation_summary"] = summary_state.summary or ""
            log_debug(f"_summarize_conversation: skipping (runs_count={summary_state.runs_count})")
            return

        history_msgs = session.get_history(num_runs=SUMMARY_THRESHOLD)
        if not history_msgs:
            log_debug("_summarize_conversation: no history available, skipping")
            summary_state.runs_count += 1
            state["summary_state"] = summary_state.model_dump()
            state["conversation_summary"] = summary_state.summary or ""
            return

        recent_msgs = history_msgs[:HISTORY_WINDOW]

        summary_input = ""
        for idx, msg in enumerate(recent_msgs):
            request_msg, response_msg = msg
            summary_input += (
                f"[Iteração {idx}]\n"
                f"Usuário: {request_msg}\n"
                f"Assistente: {response_msg}\n\n"
            )

        if user_text:
            summary_input += f"[Última Iteração]\nUsuário: {user_text}\n"

        try:
            turn = summary_agent.run(
                AgentInput(text=summary_input, session_state=state)
            )
        except Exception as exc:
            log_error(f"_summarize_conversation: agent failed: {exc}")
            summary_state.runs_count += 1
            state["summary_state"] = summary_state.model_dump()
            state["conversation_summary"] = summary_state.summary or ""
            return

        if turn and turn.content:
            summary_state.summary = turn.content
            summary_state.runs_count = 2
        else:
            log_debug("_summarize_conversation: agent returned empty content")
            summary_state.runs_count += 1

        state["summary_state"] = summary_state.model_dump()
        # Expose the running summary under a stable key so the agent's
        # dynamic instructions can read it (wrapped in <conversation_summary>
        # tags).
        state["conversation_summary"] = summary_state.summary or ""

    def _process_feedback(self, session: AgentSession, user_text: str, state: dict) -> None:
        """Run the feedback loop: satisfaction, persistence, persona.

        Mirrors the old feedback sub-workflow: evaluate the satisfaction,
        route to the matching persistence branch, then conditionally update
        the user persona. Everything mutates ``state``; nothing is returned.
        """
        self._evaluate_satisfaction(session, user_text, state)
        self._persist_feedback(state)
        self._manage_persona(session, user_text, state)

    def _evaluate_satisfaction(
        self, session: AgentSession, user_text: str, state: dict
    ) -> None:
        """Run the satisfaction agent and store the result in ``state['user_mood']``.

        On the first evaluation the result is stored under 'satisfaction';
        on subsequent evaluations (after remediation), under 'remediation'.
        """
        from semente.agents.feedback_agent import satisfaction_evaluation_agent

        history_data = session.get_history(num_runs=1)
        user_mood = state.get("user_mood", None)

        effectiveness: Optional[dict] = None

        try:
            evaluator_msg = ""
            if history_data:
                last_user_msg, last_workflow_response = history_data[0]
                evaluator_msg += "### Last Interaction ###\n"
                evaluator_msg += f"Last user message: {last_user_msg}\n\n"
                evaluator_msg += f"Last workflow response: {last_workflow_response}\n\n"
            evaluator_msg += f"Current user message: {user_text}\n"

            turn = satisfaction_evaluation_agent.run(
                AgentInput(text=evaluator_msg, session_state={"user_mood": user_mood})
            )
            if turn and turn.structured:
                effectiveness = turn.structured
        except Exception as e:
            log_error(f"_evaluate_satisfaction: agent failed: {e}")

        if effectiveness is None:
            log_debug("_evaluate_satisfaction: no effectiveness result, using default")
            effectiveness = _DEFAULT_SATISFACTION.copy()

        if user_mood is None:
            state["user_mood"] = {}
            state["user_mood"]["satisfaction"] = effectiveness
        else:
            state["user_mood"]["remediation"] = effectiveness

    def _persist_feedback(self, state: dict) -> None:
        """Persist the interaction per the satisfaction level (stub).

        TODO: implement once PositiveFeedback/NegativeFeedback tables are
        finalized and _mask_pii is available from semente.guardrails.pii_gate.
        """
        user_mood = state.get("user_mood", {})
        satisfaction = user_mood.get("satisfaction", {}) if user_mood else {}
        satisfaction_level = satisfaction.get("level", 3)

        if satisfaction_level == 5:
            # PositiveFeedback persistence (stub — see module TODO).
            log_debug("positive feedback recorded (persistence stub)")
        elif satisfaction_level == 1:
            remediation = user_mood.get("remediation", {}) if user_mood else {}
            effectiveness = (
                remediation.get("effectiveness", {})
                if isinstance(remediation, dict)
                else {}
            )
            if not effectiveness or effectiveness.get("level", 2) <= 2:
                # NegativeFeedback persistence (stub — see module TODO).
                log_debug("negative feedback recorded (persistence stub)")

    def _manage_persona(self, session: AgentSession, user_text: str, state: dict) -> None:
        """Conditionally run the persona manager agent and apply updates.

        Calls the persona manager agent only when the satisfaction level is
        >= 3, or the satisfaction is low but the remediation worked. After
        applying updates (or skipping), clears user_mood from the state.
        Name and role never change here: they are declared identity
        (onboarding tools only) — deduction does not overwrite declaration.
        """
        from semente.agents.persona_agent import persona_manager_agent
        from semente.schemas.user_persona import (
            CommunicationPreference,
            PersonaUpdate,
            UserPersona,
        )

        raw_user_mood = state.get("user_mood", None)
        if raw_user_mood is None:
            return

        try:
            user_mood = UserMood.model_validate(raw_user_mood)
        except Exception as e:
            # A malformed user_mood would stay in session_state and break
            # every later run. Drop it and move on.
            log_error(f"_manage_persona: invalid user_mood discarded: {e}")
            state["user_mood"] = None
            return

        if (
            user_mood.satisfaction.level < 3
            and user_mood.remediation
            and user_mood.remediation.effectiveness
            and user_mood.remediation.effectiveness.level < 4
        ):
            return

        try:
            turn = persona_manager_agent.run(
                AgentInput(text=user_text, session_state={"user_mood": user_mood})
            )
            if turn and turn.structured:
                # Parse the PersonaUpdate from the agent's response
                persona_update = turn.structured
                if isinstance(persona_update, dict):
                    persona_update = PersonaUpdate.model_validate(persona_update)

                # Apply updates to state["user_persona"]
                current_persona = state.get("user_persona", {})
                user_persona = (
                    UserPersona.model_validate(current_persona)
                    if current_persona
                    else UserPersona()
                )

                # Apply scalar field updates (only if non-None)
                if persona_update.regionality is not None:
                    user_persona.regionality = persona_update.regionality

                # Apply preference updates (add new, update existing)
                existing_prefs = {
                    p.key: i for i, p in enumerate(user_persona.communication_preferences)
                }
                for new_pref in persona_update.communication_preferences:
                    normalized_key = new_pref.key.strip().lower()
                    if normalized_key in existing_prefs:
                        idx = existing_prefs[normalized_key]
                        user_persona.communication_preferences[idx] = CommunicationPreference(
                            key=normalized_key,
                            description=new_pref.description,
                        )
                    else:
                        user_persona.communication_preferences.append(
                            CommunicationPreference(
                                key=normalized_key,
                                description=new_pref.description,
                            )
                        )
                        existing_prefs[normalized_key] = len(
                            user_persona.communication_preferences
                        ) - 1

                state["user_persona"] = user_persona.model_dump()

            state["user_mood"] = None

        except Exception as e:
            log_error(f"_manage_persona: agent failed: {e}")

    def _build_agent_input(
        self, session: AgentSession, user_text: str, state: dict
    ) -> str:
        """Assemble the input string for the single agent (or welcoming agent).

        Wraps the consolidated user text in ``<input>`` tags and stashes the
        dynamic conversation-history block in ``state['history_context']`` so
        the agent's dynamic instructions can read it. The history grows and
        shrinks via ``InputManager.runs_count``.
        """
        input_manager = InputManager.model_validate(state.get("summary_state", {}))

        history_msgs = session.get_history(num_runs=input_manager.runs_count)

        history_block = ""
        if history_msgs:
            history_block = "<iterações>"
            for idx, msg in enumerate(history_msgs):
                user_msg, assistant_msg = msg
                history_block += (
                    f"\n[Iteração {idx}]\n"
                    f"Usuário: {user_msg}\n"
                    f"Assistente: {assistant_msg}\n"
                )
            history_block += "</iterações>"

        state["history_context"] = history_block

        parts: list[str] = []
        if user_text:
            parts.append(f"<input>\n{user_text}\n</input>")

        return "\n".join(parts)

    def _run_single_agent(
        self,
        agent_input: str,
        images: Optional[list],
        audio: Optional[list],
        geo_files: Optional[list[File]],
        state: dict,
        user_id: str,
    ) -> StepOutput:
        """Run the single agent with the enriched input and full state."""
        if geo_files:
            log_debug(
                f"forwarding files to {getattr(self.agent, 'name', 'agent')}: "
                f"{[getattr(f, 'name', None) or getattr(f, 'filename', None) for f in geo_files]}"
            )

        return self._invoke_agent(
            self.agent,
            agent_input,
            images,
            audio,
            files=geo_files,
            state=state,
            user_id=user_id,
        )

    def _invoke_agent(
        self,
        agent: Any,
        text: str,
        images: Optional[list],
        audio: Optional[list],
        files: Optional[list[File]],
        state: dict,
        user_id: str,
    ) -> StepOutput:
        """Run one backend agent and wrap the turn as a :class:`StepOutput`.

        On agent failure, logs the error and returns a friendly message —
        the channel always has something to deliver to the user.
        """
        try:
            turn = agent.run(
                AgentInput(
                    text=text,
                    images=images or None,
                    audio=audio or None,
                    files=files,
                    session_state=state,
                    user_id=user_id,
                )
            )
        except Exception as exc:
            log_error(f"agent failed: {exc}")
            return StepOutput(
                content="Desculpa, houve um erro durante a execução. Tente novamente mais tarde!"
            )

        return StepOutput(
            content=turn.content or "",
            images=turn.images,
            videos=turn.videos,
            audio=turn.audio,
            files=turn.files,
            metrics=turn.metrics,
        )

    def _apply_remediation(self, routed: StepOutput, state: dict) -> StepOutput:
        """Merge the routed response with a remediation message when due.

        When the user is frustrated and a remediation effectiveness was
        recorded, runs the remediation agent to rewrite the response into a
        softer message (text or audio transcript). Otherwise passes the
        response through unchanged.
        """
        from semente.agents.feedback_agent import remediation_agent

        if not _should_apply_remediation(state):
            return routed

        audio_item = (
            routed.audio[0] if (routed.audio and len(routed.audio) > 0) else None
        )
        is_audio = bool(audio_item and audio_item.transcript)
        current_content = audio_item.transcript if is_audio else routed.content

        try:
            turn = remediation_agent.run(AgentInput(text=current_content))

            if is_audio:
                audio_item.transcript = turn.content
            else:
                routed.content = turn.content
        except Exception as exc:
            log_error(f"_apply_remediation: remediation agent failed - {exc}")
            return StepOutput(content="")

        return routed

    # ------------------------------------------------------------------
    # Output finalization
    # ------------------------------------------------------------------

    def _finalize_output(self, response: StepOutput, user_id: str) -> StepOutput:
        """Handle the response's voice output: transcribe it back to text and
        regenerate the synthesized speech.

        When the response carries audio, the transcript becomes the content
        and the speech is regenerated for the user (the raw engine audio is
        not echoed back).
        """
        if response.audio:
            from semente.services.audio.tts import generate_speech

            audio_transcript = "\n\n".join(a.transcript for a in response.audio)

            response.content = audio_transcript
            response.audio = [
                generate_speech(text=audio_transcript, user_id=user_id)
            ]

        return response


def _should_apply_remediation(session_state: dict) -> bool:
    """Verifica de forma segura se a remediação do humor deve ser aplicada."""
    user_mood_raw = session_state.get("user_mood")
    if not user_mood_raw:
        return False

    try:
        user_mood = UserMood.model_validate(user_mood_raw)
        return bool(user_mood.remediation and user_mood.remediation.effectiveness)
    except Exception as exc:
        log_error(f"_should_apply_remediation: failed to validate user_mood - {exc}")
        return False


def _input_as_string(input: Any) -> Optional[str]:
    """Best-effort string conversion of the raw user input."""
    if input is None:
        return None
    if isinstance(input, str):
        return input
    if isinstance(input, (dict, list)):
        return json.dumps(input, indent=2, default=str)
    return str(input)


# ---------------------------------------------------------------------------
# Factory: manifest + domain + prompts loading
# ---------------------------------------------------------------------------

def _load_domain(manifest: Manifest):
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


_agent_cache: Semente | None = None


def get_agent(manifest_path: str | None = None) -> Semente:
    """Load manifest + domain, apply language, build the agents, cache."""
    global _agent_cache
    if _agent_cache is not None:
        return _agent_cache

    import os

    if os.getenv("SEMENTE_DEMO") == "1":
        # Demo mode (``semente launch streamlit --demo``): built-in defaults, no app files.
        manifest = Manifest(name="semente-demo", engine="bare")
    else:
        path = manifest_path or os.getenv("SEMENTE_MANIFEST", "semente.yaml")
        manifest = Manifest.load(path)
    # Pin the engine BEFORE any sub-agent module is imported (they call
    # get_backend() at import time and must resolve to the manifest's engine).
    from semente.backends.registry import set_engine

    set_engine(manifest.engine)
    _apply_prompts(manifest)
    if os.getenv("SEMENTE_DEMO") == "1":
        from semente.domain import demo_domain_spec

        domain_spec = demo_domain_spec()
    else:
        domain_spec = _load_domain(manifest)

    from semente.agents.build_agent import build_agent
    from semente.agents.welcoming_agent import build_welcoming_agent
    from semente.database.session_store import store

    agent = build_agent(domain_spec, manifest)
    welcoming_agent = build_welcoming_agent(tts_enabled=manifest.features.get("tts", True))
    _agent_cache = Semente(
        agent=agent,
        welcoming_agent=welcoming_agent,
        manifest=manifest,
        store=store,
    )
    return _agent_cache