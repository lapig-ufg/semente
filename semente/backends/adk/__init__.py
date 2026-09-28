"""ADK backend — Google Agent Development Kit engine implementation.

Implements the Semente engine port on top of ``google-adk``.

Key adaptations (see MULTI_ENGINE.md §4.2):
- **Dynamic tools**: the agent (and its tool set) is built per run, resolving
  ``spec.tools`` callables against the run's session state — so Pasto Legal's
  registration-state tool switching works.
- **State seeding + sync-back**: the ADK session is seeded from Semente's
  ``input.session_state`` (the orchestrator's dict, by reference); after the
  run, ADK's state is written back into that dict in place, so tool mutations
  (terms acceptance, property registration) persist in the Semente store.
- **Tool adaptation**: Semente tools -> plain ADK functions; ``run_context`` is
  mapped to ADK's ``tool_context`` and stripped from the generated schema;
  agno toolkits (e.g. Calculator) are expanded.
- **Multimodal input**: Semente media -> ``genai`` content parts.

Known degradations (documented): skills are not wired.
"""

from __future__ import annotations

import functools
import inspect
import json
import re
from typing import Any

from semente.backends.base import Agent, AgentInput, AgentSpec, AgentTurn, EngineBackend
from semente.backends.toolkit import (
    StateContext,
    bind_args,
    build_hook_chain,
    expand_tools,
    new_media_bag,
    result_to_str,
    unwrap,
)


class _ToolContextAdapter:
    """Exposes ``session_state`` over ADK's ToolContext (which has ``.state``)."""

    def __init__(self, tool_context):
        self._tc = tool_context

    @property
    def session_state(self):
        return getattr(self._tc, "state", None) or {}

    @property
    def user_id(self):
        return getattr(self._tc, "user_id", None)


def _adapt_tool(tool, media_bag: dict, input_files: list | None = None):
    func = unwrap(tool)
    sig = inspect.signature(func)
    has_run_context = "run_context" in sig.parameters
    wants_files = "files" in sig.parameters
    hooks = getattr(tool, "tool_hooks", None) or []

    # Drop the managed ``files`` param from the visible signature (ADK builds
    # the tool declaration from it); injected at call time from input_files.
    visible_params = [p for p in sig.parameters.values() if p.name != "files"]

    chain = build_hook_chain(func, hooks, has_run_context)
    needs_ctx = has_run_context or bool(hooks)

    if not needs_ctx:

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            call_args = bind_args(sig.replace(parameters=list(sig.parameters.values())), args, kwargs)
            if wants_files:
                call_args["files"] = list(input_files or [])
            return result_to_str(chain(call_args, None), media_bag)

        wrapper.__signature__ = sig.replace(parameters=visible_params)

    else:
        # Rename run_context -> tool_context in the visible signature: ADK
        # strips the context param from the declaration itself (_ignore_params)
        # and injects the real ToolContext under that name at invocation time
        # (_prepare_invocation_args checks the signature — a param removed
        # from __signature__ would never receive the context).
        clean_sig = sig.replace(
            parameters=[
                p.replace(name="tool_context") if p.name == "run_context" else p
                for p in visible_params
            ]
        )

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            call_args = bind_args(clean_sig, args, kwargs)
            tc = call_args.pop("tool_context", None)
            ctx = _ToolContextAdapter(tc) if tc is not None else StateContext({})
            if wants_files:
                call_args["files"] = list(input_files or [])
            return result_to_str(chain(call_args, ctx), media_bag)

        # ADK builds the tool schema from the signature; make it the clean one.
        wrapper.__signature__ = clean_sig

    return wrapper


_MIME_BY_EXT = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
    ".wav": "audio/wav", ".mp3": "audio/mpeg", ".ogg": "audio/ogg", ".mp4": "video/mp4",
}


def _media_part(obj: Any, fallback_mime: str) -> Any:
    """Convert one Semente media object to a genai Part."""
    from google.genai import types

    if obj is None:
        return None
    if hasattr(obj, "content") and obj.content:
        return types.Part.from_bytes(data=obj.content, mime_type=obj.mime_type or fallback_mime)
    if hasattr(obj, "filepath") and obj.filepath:
        from pathlib import Path

        p = Path(obj.filepath)
        return types.Part.from_bytes(
            data=p.read_bytes(), mime_type=obj.mime_type or _MIME_BY_EXT.get(p.suffix.lower(), fallback_mime)
        )
    if hasattr(obj, "url") and obj.url:
        return types.Part.from_uri(file_uri=obj.url, mime_type=obj.mime_type or fallback_mime)
    return None


class AdkAgentAdapter:
    """Builds the LlmAgent per run (dynamic tools) and seeds/syncs state."""

    def __init__(self, spec: AgentSpec, app_name: str):
        self.spec = spec
        self.app_name = app_name

    def _resolve_tools(self, session_state: dict, media_bag: dict, input_files: list | None = None) -> list:
        tools_or_callable = self.spec.tools
        if callable(tools_or_callable) and not isinstance(tools_or_callable, list):
            try:
                raw = tools_or_callable(StateContext(session_state))
            except TypeError:
                raw = tools_or_callable()
        else:
            raw = tools_or_callable or []
        return [_adapt_tool(t, media_bag, input_files) for t in expand_tools(list(raw))]

    def run(self, input: AgentInput) -> AgentTurn:
        from google.adk.agents import LlmAgent
        from google.adk.runners import Runner
        from google.adk.sessions import InMemorySessionService
        from google.genai import types

        state = input.session_state if input.session_state is not None else {}
        media_bag = new_media_bag()

        instruction = self.spec.instructions
        if not callable(instruction):
            instruction = lambda ctx: str(instruction)  # noqa: E731

        def instruction_provider(ctx):
            text = instruction(_ToolContextAdapter(ctx))
            if self.spec.knowledge is not None:
                from semente.knowledge import SEARCH_KNOWLEDGE_INSTRUCTIONS

                text += (
                    "\n\n<knowledge_base>\n"
                    + SEARCH_KNOWLEDGE_INSTRUCTIONS
                    + "\n</knowledge_base>"
                )
            return text

        model = self.spec.model.model_id if self.spec.model else "gemini-2.5-flash"

        tools = self._resolve_tools(state, media_bag, input_files=list(input.files or []))
        if self.spec.knowledge is not None:
            from semente.knowledge import build_search_tool

            tools.append(_adapt_tool(build_search_tool(self.spec.knowledge), media_bag))

        agent = LlmAgent(
            model=model,
            name=_sanitize_name(self.spec.name),
            instruction=instruction_provider,
            tools=tools,
            output_schema=self.spec.output_schema,
        )

        session_service = InMemorySessionService()
        # Seed the ADK session from Semente's state (same dict, by reference).
        session = _sync(
            session_service.create_session(
                app_name=self.app_name,
                user_id=input.user_id or "default",
                state=dict(state),
            )
        )
        runner = Runner(agent=agent, app_name=self.app_name, session_service=session_service)

        parts = [types.Part(text=input.text)] if input.text else []
        for img in input.images or []:
            part = _media_part(img, "image/png")
            if part:
                parts.append(part)
        for aud in input.audio or []:
            part = _media_part(aud, "audio/wav")
            if part:
                parts.append(part)
        content = types.Content(role="user", parts=parts or [types.Part(text="")])

        final_text = ""
        for event in runner.run(
            user_id=input.user_id or "default",
            session_id=session.id,
            new_message=content,
        ):
            if event.is_final_response() and event.content and event.content.parts:
                final_text = "".join(p.text for p in event.content.parts if p.text)

        # Sync ADK's (possibly tool-mutated) state back into Semente's dict.
        try:
            updated = _sync(
                session_service.get_session(
                    app_name=self.app_name,
                    user_id=input.user_id or "default",
                    session_id=session.id,
                )
            )
            if updated is not None and getattr(updated, "state", None):
                state.clear()
                state.update({k: v for k, v in updated.state.items() if not k.startswith(("temp:",))})
        except Exception:
            pass

        structured = None
        if self.spec.output_schema and final_text:
            try:
                structured = json.loads(final_text)
            except json.JSONDecodeError:
                structured = None

        return AgentTurn(
            content=final_text,
            structured=structured,
            images=media_bag["images"] or None,
            videos=media_bag["videos"] or None,
            audio=media_bag["audios"] or None,
            files=media_bag["files"] or None,
        )


def _sanitize_name(name: str) -> str:
    """ADK node names must be valid Python identifiers."""
    return re.sub(r"\W+", "_", name).strip("_") or "agent"


def _sync(coro_or_val):
    """ADK >= 2.8 session service methods are async; older ones are sync.
    Works with either (the workflow runs synchronously, so we drive the
    coroutine on a fresh loop)."""
    import asyncio
    import inspect

    if inspect.iscoroutine(coro_or_val):
        return asyncio.run(coro_or_val)
    return coro_or_val


class AdkBackend(EngineBackend):
    name = "adk"

    def build_agent(self, spec: AgentSpec) -> Agent:
        return AdkAgentAdapter(spec, app_name=spec.name)

    def supports(self, capability: str) -> bool:
        return capability in {"structured_output", "multimodal_in"}