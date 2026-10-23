"""Harness — the single-object pipeline that replaces the workflow engine.

One object owns the whole conversation turn: ``run()`` is a thin sequencer
and each unique stage of the old workflow is a private method whose return
value is passed explicitly to the next call (no ``StepInput`` thread-local
registry, no step-name lookups).

Pipeline (feature toggles from the manifest ``features`` in parentheses):

    _input_preprocessing   media -> text, geo files -> GeoJSON (always)
    _run_input_guardrails  pluggable guardrail chain: redaction or a
                           blocked turn with a reply (guardrails)
    _needs_onboarding      terms + profile gate (always)
    ├─ True:  _run_welcoming_agent
    └─ False: _summarize_conversation (summarization)
              _process_feedback      (interaction_assessment; returns whether a
                                       remediation cycle is open: frustration
                                       detected and the user did not change
                                       the topic)
              _run_single_agent      (always; sees summary + history; gets a
                                       "generate a better answer" instruction
                                       appended when the cycle is open)
              _generate_apology      (part of the feedback loop: apology,
                                      new answer and evaluation request)
    _finalize_output       audio transcripts -> synthesized voice (tts)
    _persist_session       state + history back to the store
    _finalize_pending_history  closed DPO cycle -> ``history`` on the row

The DPO feedback works in two turns. On frustration (turn n) the rejected
half is registered right away (NegativeFeedback: ``prompt`` + ``rejected``,
``chosen`` empty, ``approved`` unset) and
``assessment.pending`` carries the record id plus the replacement answer
after the agent runs — and ``cycle_start``, the index where the cycle began.
On the next turn, if the user evaluates the new answer positively, the
stored row is completed with ``chosen`` (approved); on a negative evaluation
the row is kept as a failed remediation (not for training). Either way the
pending is marked closed and the cycle's history (up to 3 runs, from the
moment the frustration was noticed) is written onto the row when the turn
ends.

Media/summary/feedback/persona agents are imported lazily *inside* the
methods: their modules build agents at import time, so they must only be
imported after the language/prompts dir has been applied (``get_harness``).

External interface:
    Harness  -- the harness object the channels call.
    get_harness     -- manifest + domain + prompts loading, cached singleton.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any, Optional

from semente.backends.base import AgentInput
from semente.configs.prompts import set_prompts_dir
from semente.core.types import Session, SessionStore, StepOutput
from semente.guardrails.base import GuardrailChain, GuardrailContext, GuardrailResult
from semente.logging import log_debug, log_error, log_info
from semente.manifest import Manifest
from semente.schemas.input_manager import InputManager
from semente.schemas.interaction_assessment import (
    InteractionAssessment,
    PendingFeedback,
)
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
_DEFAULT_SATISFACTION = {
    "level": 3,
    "level_message": "Neutral (default)",
    "changed_topic": False,
}

# Appended to the agent input on the turn that opens a remediation cycle:
# the user disliked the last answer but stayed on the topic. The agent
# should genuinely retry, never apologize (the apology is a separate step),
# and move on to the next topic only when no better answer is possible.
_REMEDIATION_INSTRUCTION = (
    "<feedback_instruction>\n"
    "ATTENTION: the user rated the previous answer poorly and did NOT change the topic.\n"
    "Generate a better answer for the last question, fixing the reported problem.\n"
    "Do NOT apologize and do NOT mention the dissatisfaction — deliver only the new answer.\n"
    "If there is no way to generate a better answer, move on to the next topic.\n"
    "</feedback_instruction>"
)


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
                "An unexpected error occurred while processing the uploaded file. "
                "Try again with a different file."
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
# Harness
# ---------------------------------------------------------------------------

class Harness:
    """The whole conversation pipeline as a single object.

    Args:
        agent: The single backend agent built from the DomainSpec.
        welcoming_agent: The onboarding agent (terms + persona stages).
        manifest: The parsed ``semente.yaml`` — name and feature toggles.
        store: Optional :class:`SessionStore` for cross-run persistence.
        guardrails: The :class:`GuardrailChain` composed from the domain's
            ``DomainSpec.guardrails`` — one chain re-used by the pipeline, the
            channels (door redaction/masking), and the persistence sanitization.
    """

    def __init__(
        self,
        agent: Any,
        welcoming_agent: Any,
        manifest: Manifest,
        store: Optional[SessionStore] = None,
        guardrails: Optional["GuardrailChain"] = None,
    ):
        self.agent = agent
        self.welcoming_agent = welcoming_agent
        self.name = manifest.name
        self.features = manifest.features or {}
        self.store = store
        self.guardrails = guardrails or GuardrailChain([])

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    @property
    def _chain(self) -> Optional[GuardrailChain]:
        """The active guardrail chain (feature toggle + non-empty list)."""
        if not self.guardrails.enabled:
            return None
        if not self.features.get("guardrails", True):
            return None
        return self.guardrails

    def redact(self, text: str) -> tuple[str, list[str]]:
        """Door redaction for the channels: ``(text, removed types)``.

        The channel is the only place raw text touches logs, cache, or the
        persistence layer *before* the pipeline — so it redacts here, through
        the same chain the pipeline will use.
        """
        chain = self._chain
        if chain is None:
            return text or "", []
        result = chain.redact(GuardrailContext(text=text or "", source="channel"))
        return result.text, result.removed

    def mask(self, text: str) -> str:
        """Log masking through the active chain (identity when off)."""
        chain = self._chain
        if chain is None:
            return text or ""
        return chain.mask(text or "")

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
            log_debug("Harness.run(stream=True): running synchronously.")

        session: Session = self._load_session(user_id, session_id, session_state)

        user_text, geo_files = self._input_preprocessing(input, images, audio, files)

        guardrail_block: Optional[GuardrailResult] = None
        if self.features.get("guardrails", True):
            user_text, guardrail_block = self._run_input_guardrails(user_text, session)

        if guardrail_block is not None:
            final = StepOutput(content=guardrail_block.response or "")
        elif self._needs_onboarding(session.session_state, user_id):
            final = self._run_welcoming_agent(session, user_text, images, audio)
        else:
            needs_remediation = False
            if self.features.get("summarization", True):
                self._summarize_conversation(session, user_text, session.session_state)
            if self._interaction_assessment_enabled():
                needs_remediation = self._process_feedback(session, user_text, session.session_state)
            agent_input = self._build_agent_input(
                session, user_text, session.session_state, needs_remediation
            )
            # Cycle turns (the frustration turn + the turn evaluating the
            # remediation) and onboarding are never recorded as clean SFT
            # trajectories.
            assessment = session.interaction_assessment
            cycle_turn = needs_remediation or (
                assessment is not None and assessment.pending is not None
            )
            routed = self._run_single_agent(
                agent_input, images, audio, geo_files,
                session.session_state, user_id, record=not cycle_turn,
            )

            # The plain new answer (before the apology) is what completes
            # the DPO pair; store it now, apology generation may fail.
            if (
                assessment and assessment.pending and not assessment.pending.closed
                and not assessment.pending.new_response
            ):
                assessment.pending.new_response = routed.content or (
                    "\n".join(
                        a.transcript for a in (routed.audio or []) if a.transcript
                    )
                )

            if needs_remediation:
                routed = self._generate_apology(routed)

            final = routed

        final = self._finalize_output(final, user_id)
        self._persist_session(session, input, final)
        self._finalize_pending_history(session)
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
    ) -> Session:
        """Load the (store-backed) session, or start a fresh one."""
        if self.store is not None:
            loaded = self.store.get(user_id, session_id)
            if loaded is not None:
                return Session(
                    user_id=user_id,
                    session_id=session_id,
                    session_state=loaded.get("session_state", {}),
                    runs=loaded.get("runs", []),
                    interaction_assessment=loaded.get("interaction_assessment"),
                )
        return Session(
            user_id=user_id,
            session_id=session_id,
            session_state=session_state or {},
        )

    def _persist_session(self, session: Session, user_input: Any, final: StepOutput) -> None:
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
            interaction_assessment=session.interaction_assessment,
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
        the pipeline guardrail stage: the redacted text is what gets persisted
        in the run history, so redacting one stage later would leave a raw
        copy in the database. Typed text arrives already redacted at the
        channel doors (MessageContent __post_init__ in whatsapp/helpers;
        streamlit_webapp).
        """
        parts: list[str] = []

        texto = _input_as_string(input)
        if texto:
            parts.append(texto)

        if images:
            from semente.agents.media_agents import image_description_agent

            try:
                turn = image_description_agent.run(AgentInput(text="", images=images))
                # Redacted HERE, not in the guardrail stage: the
                # transcription/description is what gets persisted in the run
                # history, which is stored. Redacting only in the next stage
                # would leave a raw copy in the database.
                description = self._run_media_guardrails(turn.content or "", "image")
                log_debug(f"Image description: {description}")
                if description:
                    parts.append(f"[IMAGEM]{description}[/IMAGEM]")
            except Exception as e:
                log_error(f"image description failed: {e}")

        if audio:
            from semente.agents.media_agents import audio_transcription_agent

            try:
                turn = audio_transcription_agent.run(AgentInput(text="", audio=audio))
                # Same reason as the image description: redact before persisting.
                transcription = self._run_media_guardrails(turn.content or "", "audio")
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
                    f"[GEOSPATIAL FILE]The uploaded file could not be processed: "
                    f"{error}[/GEOSPATIAL FILE]"
                )

        return "\n".join(parts), geo_files

    # ------------------------------------------------------------------
    # Guardrail chain
    # ------------------------------------------------------------------

    def _run_input_guardrails(
        self, user_text: str, session: Session
    ) -> tuple[str, Optional[GuardrailResult]]:
        """Run the pluggable guardrail chain on the consolidated text.

        The user keeps the requests they made in the same message, and the
        datum never reaches the agent. Returns ``(text, blocked_result)``:
        when a guard blocks, ``text`` is the guarded text (kept for
        persistence) and ``blocked_result.response`` is the user-facing reply
        — the agent never runs that turn. Typed text is also redacted at the
        channel doors; this stage additionally covers what only became text
        inside this turn (audio transcription, image description).

        Logging: one ``INFO`` summary per turn — the turn outcome at a glance
        (guardrail count, clean/redacted/blocked); per-guard detail goes to
        ``DEBUG`` (visible with ``APP_ENV=development``).
        """
        if not self._chain:
            log_debug("guardrails[pipeline]: feature off or no guards declared")
            return user_text, None

        log_debug(
            f"guardrails[pipeline]: running {len(self._chain.guardrails)} guard(s) "
            f"on {len(user_text)} char(s)"
        )
        result = self._chain.redact(
            GuardrailContext(
                text=str(user_text),
                session_state=session.session_state,
                user_id=session.user_id,
                source="pipeline",
            )
        )
        if result.blocked:
            log_info(
                f"guardrails[pipeline]: BLOCKED by ({', '.join(result.removed) or 'unknown'}) "
                "— agent skipped, refusal reply sent"
            )
            return result.text, result
        if result.removed:
            # Only the types, never the values.
            log_info(f"guardrails[pipeline]: removed ({', '.join(result.removed)})")
        else:
            log_info(f"guardrails[pipeline]: {len(self._chain.guardrails)} guard(s) ran — clean")
        return result.text, None

    def _run_media_guardrails(self, text: str, label: str) -> str:
        """Guardrail redaction on media-derived text (transcription/description).

        Blocking cannot happen here by design: the media text joins other
        input parts and a whole-turn refusal is decided at the pipeline
        stage — here a ``blocked`` guard is logged and its (redacted) text is
        still used, so the raw value is never persisted.
        """
        chain = self._chain
        if chain is None:
            return text
        result = chain.redact(GuardrailContext(text=text, source="media"))
        if result.blocked:
            log_info(
                "guardrails[media]: a guard reported a block for media-derived "
                f"text (label={label}) — media cannot block the turn; keeping "
                "the redacted text"
            )
        elif result.removed:
            log_info(f"guardrails[media:{label}]: removed ({', '.join(result.removed)})")
        return result.text

    def _sanitize(self, data):
        """Sanitize persisted JSON-like data through the active chain."""
        if self._chain is None:
            return data
        after = self._chain.sanitize_json(data)
        try:
            if json.dumps(data, default=str) != json.dumps(after, default=str):
                log_debug("guardrails[persistence]: sensitive spans redacted before persistence")
        except TypeError:
            pass
        return after

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
                acceptance = db_session.query(UserTermsAcceptance).filter(
                    UserTermsAcceptance.user_id == user_id,
                    UserTermsAcceptance.accepted == True,  # noqa: E712
                ).first()

                if not acceptance:
                    return True

                state["terms_accepted"] = True

            if not is_persona_complete(persona):
                profile = db_session.query(UserProfile).filter(
                    UserProfile.user_id == user_id
                ).first()

                if profile is None:
                    return True

                # Fill only the fields still missing (or still holding the
                # schema sentinel), preserving values the agent just wrote
                # this session.
                for field in ("name", "role"):
                    if not is_persona_field_informed(persona.get(field)) and getattr(profile, field):
                        persona[field] = getattr(profile, field)

                state["user_persona"] = persona

            return not is_persona_complete(state.get("user_persona") or {})
        finally:
            db_session.close()

    # ------------------------------------------------------------------
    # Agent stages
    # ------------------------------------------------------------------

    def _run_welcoming_agent(
        self,
        session: Session,
        user_text: str,
        images: Optional[list],
        audio: Optional[list],
    ) -> StepOutput:
        """Run the staged welcoming agent (terms, then persona).

        Onboarding turns (terms acceptance, persona setup) are SFT noise:
        they are never recorded into ``recent_agent_runs``.
        """
        return self._invoke_agent(
            self.welcoming_agent,
            self._build_agent_input(session, user_text, session.session_state),
            images,
            audio,
            files=None,
            state=session.session_state,
            user_id=session.user_id,
            record=False,
        )

    def _summarize_conversation(
        self, session: Session, user_text: str, state: dict
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
                f"[Iteration {idx}]\n"
                f"User: {request_msg}\n"
                f"Assistant: {response_msg}\n\n"
            )

        if user_text:
            summary_input += f"[Last Iteration]\nUser: {user_text}\n"

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
        
    def _interaction_assessment_enabled(self) -> bool:
        """The interaction_assessment gate: bool or {enable, window_size}."""
        value = self.features.get("interaction_assessment", True)
        if hasattr(value, "enable"):
            return value.enable
        if isinstance(value, dict):
            return value.get("enable", True)
        return bool(value)

    def _process_feedback(
        self, session: Session, user_text: str, state: dict
    ) -> bool:
        """Run the feedback loop: satisfaction, persistence, persona.

        Mirrors the old feedback sub-workflow: evaluate the satisfaction,
        route to the matching persistence branch, then conditionally update
        the user persona. Everything mutates the session's assessment.

        Returns True when a remediation cycle needs to run this turn (the
        user is frustrated **and** did not change the topic) — the caller
        then injects the retry instruction and runs the apology step.
        """
        self._evaluate_satisfaction(session, user_text)
        needs_remediation = self._persist_feedback(session)
        self._manage_persona(session, user_text, state)
        return needs_remediation

    def _evaluate_satisfaction(
        self, session: Session, user_text: str
    ) -> None:
        """Run the satisfaction agent and store the result on the session.

        The result also carries the topic check (``changed_topic``): it
        decides whether a frustration opens a remediation cycle. The open
        DPO pair (``pending``) is carried over from the previous
        assessment — this turn's message may be its evaluation.
        """
        from semente.agents.feedback_agent import satisfaction_evaluation_agent
        from semente.schemas.interaction_assessment import Effectiveness

        history_data = session.get_history(num_runs=1)
        prior = session.interaction_assessment
        pending = prior.pending if prior else None
        # A closed pending is a leftover awaiting only the history
        # finalizer — it is never an evaluation turn, but it must be
        # carried so the finalizer can retry writing the row's history.
        has_pending = pending is not None and not pending.closed

        effectiveness: Optional[Effectiveness] = None

        try:
            evaluator_msg = ""
            if history_data:
                last_user_msg, last_workflow_response = history_data[0]
                evaluator_msg += "### Last Interaction ###\n"
                evaluator_msg += f"Last user message: {last_user_msg}\n\n"
                evaluator_msg += f"Last workflow response: {last_workflow_response}\n\n"
            evaluator_msg += f"Current user message: {user_text}\n"

            turn = satisfaction_evaluation_agent.run(
                AgentInput(
                    text=evaluator_msg,
                    session_state={"pending_feedback": has_pending},
                )
            )
            if turn and turn.structured:
                effectiveness = turn.structured
                if isinstance(effectiveness, dict):
                    effectiveness = Effectiveness.model_validate(effectiveness)
        except Exception as e:
            log_error(f"_evaluate_satisfaction: agent failed: {e}")

        if effectiveness is None:
            log_debug("_evaluate_satisfaction: no effectiveness result, using default")
            effectiveness = Effectiveness.model_validate(_DEFAULT_SATISFACTION)

        session.interaction_assessment = InteractionAssessment(
            satisfaction=effectiveness,
            pending=pending,
        )

    def _persist_feedback(self, session: Session) -> bool:
        """Persist the interaction per the satisfaction level (DPO two-phase).

        The DPO pair is captured across two turns:

        - Turn n (level <= 2): insert a NegativeFeedback row right away with
          the rejected half (``prompt`` + ``rejected``; ``chosen`` empty),
          where the pair comes from the last history run (the exchange that
          generated the frustration). ``assessment.pending`` carries the
          record id so the row can be completed later; ``run()`` fills
          ``new_response`` after the agent runs. Also returned: True when a
          remediation cycle is open (frustration and the user did not change
          topic).
        - Turn n + 1: if ``assessment.pending`` exists (and is not closed),
          this turn is the user's evaluation of the new answer. Positive
          (level >= 4) completes the stored row with ``chosen`` and
          ``approved: true``; negative (level <= 2) marks the row as a failed
          remediation — ``approved: false`` plus the rejected new answer
          (``rejected_new``) — kept for manual analysis, not for training.
          Neutral leaves the row untouched. Either way the pending is marked
          closed: :meth:`_finalize_pending_history` (called after the run is
          appended to ``session.runs``) writes the cycle's ``history`` onto
          the row and drops the pending. NO new cycle opens this turn — if
          the user remains frustrated, a fresh cycle opens on the following
          turn.

        The SFT branch (positive satisfaction -> PositiveFeedback with the
        history of the recent clean runs) only sees clean, non-cycle turns:
        cycle turns and onboarding are never recorded into
        ``recent_agent_runs``.
        """
        import datetime
        from semente.database.models import NegativeFeedback, PositiveFeedback
        from semente.database.session import SessionLocal, engine

        # The legacy feedback tools used to create the feedback tables via
        # create_all; after their removal the harness owns table creation.
        NegativeFeedback.metadata.create_all(bind=engine)

        state = session.session_state
        assessment = session.interaction_assessment
        if assessment is None:
            return False
        satisfaction = assessment.satisfaction
        satisfaction_level = satisfaction.level
        changed_topic = satisfaction.changed_topic

        recent_runs = state.get("recent_agent_runs", [])

        db_session = SessionLocal()
        try:
            # A pending pair that is not closed makes this turn the
            # evaluation turn: consume it and never open a new cycle on
            # the same turn. The row gains the evaluation outcome:
            # ``approved: True`` with the new answer as ``chosen``
            # (positive evaluation -> completed DPO pair), or
            # ``approved: False`` plus ``rejected_new`` (failed
            # remediation -> kept for manual analysis, not for training).
            # The pending is marked closed (not dropped): the history
            # finalizer still needs its record_id + cycle_start to write
            # the cycle's history.
            pending = assessment.pending
            if pending is not None and pending.closed:
                # Leftover from a failed finalization — not an eval turn.
                pending = None
            evaluation_turn = pending is not None
            if pending:
                if satisfaction_level >= 4 and pending.new_response:
                    record = db_session.get(NegativeFeedback, pending.record_id)
                    if record is not None:
                        record.chosen = self._sanitize(pending.new_response)
                        record.approved = True
                        db_session.commit()
                        log_debug(
                            "pending negative feedback completed with the "
                            "chosen response (DPO pair approved)"
                        )
                elif satisfaction_level <= 2 and pending.new_response:
                    # Failed remediation: useless for training (no chosen)
                    # but valuable for manual analysis of repeated issues.
                    record = db_session.get(NegativeFeedback, pending.record_id)
                    if record is not None:
                        record.rejected_new = self._sanitize(pending.new_response)
                        record.approved = False
                        db_session.commit()
                        log_debug(
                            "pending negative feedback kept as a failed "
                            "remediation (approved=false, not for training)"
                        )
                pending.closed = True

            if satisfaction_level >= 4 and recent_runs:
                sanitized_history = self._sanitize(recent_runs)
                feedback_record = PositiveFeedback(
                    timestamp=datetime.datetime.utcnow().isoformat(),
                    history=sanitized_history,
                    grade=satisfaction_level,
                )
                db_session.add(feedback_record)
                db_session.commit()
                log_debug("positive feedback recorded (SFT dataset)")

            if satisfaction_level <= 2 and not evaluation_turn:
                history = session.get_history(num_runs=1)
                if history:
                    prompt, rejected = history[0]
                    feedback_record = NegativeFeedback(
                        timestamp=datetime.datetime.utcnow().isoformat(),
                        prompt=self._sanitize(prompt),
                        rejected=self._sanitize(rejected),
                        chosen="",
                    )
                    db_session.add(feedback_record)
                    db_session.commit()
                    # Everything about the interaction assessment stays in
                    # one object: the pending pair rides the assessment
                    # (persisted on its own DB column), not session_state.
                    assessment.pending = PendingFeedback(
                        record_id=feedback_record.id,
                        # The frustration run itself will be appended by
                        # _persist_session right after this turn — the
                        # cycle's history starts exactly there.
                        cycle_start=len(session.runs),
                    )
                    log_debug(
                        "negative feedback registered with the rejected "
                        "answer (DPO pair pending chosen)"
                    )

        except Exception as e:
            log_error(f"_persist_feedback failed: {e}")
            db_session.rollback()
            return False
        finally:
            db_session.close()

        return (
            satisfaction_level <= 2 and not changed_topic and not evaluation_turn
        )

    def _finalize_pending_history(self, session: Session) -> None:
        """Write the frustration cycle's ``history`` onto the stored row.

        Called after ``_persist_session`` so the evaluation run is already
        in ``session.runs``: the history is the (up to 3) ``{user,
        assistant}`` runs from ``pending.cycle_start`` (the moment the
        system noticed the frustration) onward. On success (or when there
        is nothing to write) the pending is dropped; on failure it stays
        closed so a later turn can retry.
        """
        assessment = session.interaction_assessment
        if assessment is None or assessment.pending is None:
            return
        pending = assessment.pending
        if not pending.closed:
            return

        from semente.database.models import NegativeFeedback
        from semente.database.session import SessionLocal, engine

        NegativeFeedback.metadata.create_all(bind=engine)

        history = [
            {"user": run.get("user", ""), "assistant": run.get("assistant", "")}
            for run in session.runs[pending.cycle_start:][:3]
        ]

        db_session = SessionLocal()
        try:
            if history:
                record = db_session.get(NegativeFeedback, pending.record_id)
                if record is not None:
                    record.history = self._sanitize(history)
                    db_session.commit()
                    log_debug("frustration cycle history written (max 3 runs)")
            assessment.pending = None
        except Exception as e:
            log_error(f"_finalize_pending_history failed: {e}")
            db_session.rollback()  # pending stays closed for a retry
        finally:
            db_session.close()

    def _manage_persona(self, session: Session, user_text: str, state: dict) -> None:
        """Conditionally run the persona manager agent and apply updates.

        Runs the persona manager only when the user is not frustrated
        (satisfaction >= 3). The assessment is NOT cleared here: it is
        replaced wholesale by ``_evaluate_satisfaction`` on the next turn,
        and its ``pending`` DPO pair must survive until it is consumed by
        ``_persist_feedback`` on the evaluation turn. Name and role never
        change here: they are declared identity (onboarding tools only) —
        deduction does not overwrite declaration.
        """
        from semente.agents.persona_agent import persona_manager_agent
        from semente.schemas.user_persona import (
            CommunicationPreference,
            PersonaUpdate,
            UserPersona,
        )

        assessment = session.interaction_assessment
        if assessment is None:
            return

        # A malformed assessment would break every subsequent comparison.
        # Drop it and move on.
        if not isinstance(assessment, InteractionAssessment):
            try:
                assessment = InteractionAssessment.model_validate(assessment)
                session.interaction_assessment = assessment
            except Exception as e:
                log_error(f"_manage_persona: invalid assessment discarded: {e}")
                session.interaction_assessment = None
                return

        try:
            if assessment.satisfaction.level >= 3:
                turn = persona_manager_agent.run(
                    AgentInput(
                        text=user_text,
                        session_state={"interaction_assessment": assessment.model_dump()},
                    )
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

        except Exception as e:
            log_error(f"_manage_persona: agent failed: {e}")

    def _build_agent_input(
        self,
        session: Session,
        user_text: str,
        state: dict,
        remediate: bool = False,
    ) -> str:
        """Assemble the input string for the single agent (or welcoming agent).

        Wraps the consolidated user text in ``<input>`` tags and stashes the
        dynamic conversation-history block in ``state['history_context']`` so
        the agent's dynamic instructions can read it. The history grows and
        shrinks via ``InputManager.runs_count``. When ``remediate`` is set
        (frustration detected and the user did not change the topic), a
        ``<feedback_instruction>`` block is appended: the agent must generate
        a better answer without apologizing, or move on to the next topic.
        """
        input_manager = InputManager.model_validate(state.get("summary_state", {}))

        history_msgs = session.get_history(num_runs=input_manager.runs_count)

        history_block = ""
        if history_msgs:
            history_block = "<iterations>"
            for idx, msg in enumerate(history_msgs):
                user_msg, assistant_msg = msg
                history_block += (
                    f"\n[Iteration {idx}]\n"
                    f"User: {user_msg}\n"
                    f"Assistant: {assistant_msg}\n"
                )
            history_block += "</iterations>"

        state["history_context"] = history_block

        parts: list[str] = []
        if user_text:
            parts.append(f"<input>\n{user_text}\n</input>")

        if remediate:
            parts.append(_REMEDIATION_INSTRUCTION)

        return "\n".join(parts)

    @staticmethod
    def _raw_user_text(text: str) -> str:
        """Extract the raw user message from the decorated agent input.

        The agent input wraps the user text in ``<input>`` tags and may
        append a ``<feedback_instruction>`` block. SFT trajectories must
        store only what the user actually said, so the wrappers are stripped
        (falling back to tag removal when the extraction fails).
        """
        start = text.find("<input>")
        if start != -1:
            start += len("<input>")
            end = text.find("</input>", start)
            if end != -1 and text[start:end].strip():
                return text[start:end].strip()
        raw = text.split("<feedback_instruction>")[0]
        return raw.replace("<input>", "").replace("</input>", "").strip()

    def _run_single_agent(
        self,
        agent_input: str,
        images: Optional[list],
        audio: Optional[list],
        geo_files: Optional[list[File]],
        state: dict,
        user_id: str,
        record: bool = True,
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
            record=record,
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
        record: bool = True,
    ) -> StepOutput:
        """Run one backend agent and wrap the turn as a :class:`StepOutput`.

        On agent failure, logs the error and returns a friendly message —
        the channel always has something to deliver to the user. When
        ``record`` is set, the turn is appended to
        ``state['recent_agent_runs']`` (the SFT trajectory source): onboarding
        and remediation-cycle turns pass ``record=False`` so they never
        pollute the clean-turn history.
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

            feedback_config = self.features.get("interaction_assessment", {})
            is_enabled = False
            window_size = 5

            if hasattr(feedback_config, "enable"):
                is_enabled = feedback_config.enable
                window_size = getattr(feedback_config, "window_size", 5)
            elif isinstance(feedback_config, dict):
                is_enabled = feedback_config.get("enable", True)
                window_size = feedback_config.get("window_size", 5)

            if is_enabled and record:
                turn_record = {
                    # Store the RAW user text: the decorated ``text`` carries
                    # XML wrappers (<input>, <feedback_instruction>) that are
                    # meaningless for training data.
                    "user": self._raw_user_text(text),
                    "assistant": turn.content or "",
                    "tools": [],
                    "messages": []
                }
                
                if hasattr(turn, "tools") and turn.tools:
                    for tool in turn.tools:
                        turn_record["tools"].append({
                            "tool_name": getattr(tool, "tool_name", "unknown"),
                            "tool_args": getattr(tool, "tool_args", {}),
                            "result": getattr(tool, "result", None)
                        })
                        
                if hasattr(turn, "messages") and turn.messages:
                    for msg in turn.messages:
                        msg_dict = {
                            "role": getattr(msg, "role", "unknown"),
                            "content": getattr(msg, "content", None)
                        }
                        if hasattr(msg, "tool_calls") and msg.tool_calls:
                            msg_dict["tool_calls"] = msg.tool_calls
                        turn_record["messages"].append(msg_dict)
                
                recent_runs = state.get("recent_agent_runs", [])
                recent_runs.append(turn_record)
                
                if len(recent_runs) > window_size:
                    recent_runs = recent_runs[-window_size:]
                    
                state["recent_agent_runs"] = recent_runs
                
        except Exception as exc:
            log_error(f"agent failed: {exc}")
            return StepOutput(
                content="Sorry, there was an error during execution. Please try again later!"
            )

        return StepOutput(
            content=turn.content or "",
            images=turn.images,
            videos=turn.videos,
            audio=turn.audio,
            files=turn.files,
            metrics=turn.metrics,
        )
        
    def _generate_apology(self, routed: StepOutput) -> StepOutput:
        """Wrap the new answer with an apology + evaluation request.

        Runs the remediation agent on the plain new answer. The agent's
        output has three parts separated by ``[PAUSE]``: the apology, the
        answer (echoed unchanged), and the evaluation call-to-action. The
        final message keeps the fixed order: FIRST the apology, THEN the
        new answer, THEN the evaluation request at the end.

        On failure the main answer is still delivered unchanged.
        """
        from semente.agents.feedback_agent import remediation_agent
        from semente.tools.types import Audio

        base = routed.content or ""
        if not base and routed.audio:
            base = "\n".join(a.transcript for a in routed.audio if a.transcript)
        if not base:
            return routed

        try:
            turn = remediation_agent.run(AgentInput(text=base))
            raw = (turn.content or "").split("[PAUSE]")
            apology = raw[0].strip()
            evaluation = raw[2].strip() if len(raw) > 2 else ""
            final = "\n\n".join(p for p in (apology, base, evaluation) if p)
        except Exception as exc:
            log_error(f"_generate_apology: remediation agent failed - {exc}")
            return routed

        if not final or final == base:
            return routed

        routed.content = final

        if routed.audio:
            routed.audio = [
                Audio(transcript=p)
                for p in (apology, base, evaluation)
                if p.strip()
            ]

        return routed

    # ------------------------------------------------------------------
    # Output finalization
    # ------------------------------------------------------------------

    def _finalize_output(self, response: StepOutput, user_id: str) -> StepOutput:
        """Handle the response's voice output: transcribe it back to text and
        regenerate the synthesized speech.

        When the response carries audio, each item's transcript becomes the
        content and the speech is regenerated per item (the raw engine audio
        is not echoed back). Audio items are kept in order, so a remediated
        turn arrives as [apology, new answer, evaluation request].
        """
        if response.audio:
            from semente.services.audio.tts import generate_speech

            transcripts = [a.transcript or "" for a in response.audio]
            response.content = "\n\n".join(transcripts)
            response.audio = [
                speech
                for speech in (
                    generate_speech(text=transcript, user_id=user_id)
                    for transcript in transcripts
                    if transcript.strip()
                )
                if speech is not None
            ]

        return response


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


_harness_cache: Harness | None = None


def get_harness(manifest_path: str | None = None) -> Harness:
    """Load manifest + domain, apply language, build the agents, cache."""
    global _harness_cache
    if _harness_cache is not None:
        return _harness_cache

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
    from semente.guardrails import GuardrailChain, set_active_chain

    agent = build_agent(domain_spec, manifest)
    welcoming_agent = build_welcoming_agent(tts_enabled=manifest.features.get("tts", True))
    guardrails = GuardrailChain(domain_spec.guardrails)
    set_active_chain(guardrails)
    _harness_cache = Harness(
        agent=agent,
        welcoming_agent=welcoming_agent,
        manifest=manifest,
        store=store,
        guardrails=guardrails,
    )
    return _harness_cache