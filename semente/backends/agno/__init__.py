"""Agno backend — the reference engine implementation.

Implements the Semente engine port (``EngineBackend``) on top of Agno. All
Agno imports for agent construction live here; the rest of Semente is
engine-free. Native Semente ``Tool``s are converted to agno ``Function``s at
this boundary.
"""

from __future__ import annotations

import functools
import inspect
from typing import Any

from agno.agent import Agent as AgnoAgent
from agno.media import Audio as EAudio
from agno.media import File as EFile
from agno.media import Image as EImage
from agno.tools.function import Function

from semente.backends.agno.media import to_engine_media, to_engine_result
from semente.backends.agno.models import build_model
from semente.backends.base import Agent, AgentInput, AgentSpec, AgentTurn, EngineBackend
from semente.backends.toolkit import tool_schema
from semente.configs.config import config
from semente.tools.types import Tool


def _build_model(spec_model):
    if spec_model is None:
        return build_model(config.PRIMARY_MODEL_PROVIDER, config.PRIMARY_MODEL_ID)
    return build_model(spec_model.provider, spec_model.model_id)


def _wrap_result_conversion(func):
    """Wrap a raw tool func so its Semente ToolResult becomes an agno ToolResult."""
    if inspect.iscoroutinefunction(func):

        @functools.wraps(func)
        async def wrapped(*args, **kwargs):
            return to_engine_result(await func(*args, **kwargs))

    else:

        @functools.wraps(func)
        def wrapped(*args, **kwargs):
            return to_engine_result(func(*args, **kwargs))

    return wrapped


def _to_agno_function(tool: Tool) -> Function:
    """Convert a native Tool to an agno Function (schema built by the shared seam)."""
    schema = tool_schema(tool)
    return Function(
        name=schema["name"],
        description=schema["description"],
        parameters=schema["parameters"],
        entrypoint=_wrap_result_conversion(tool.func),
        tool_hooks=tool.tool_hooks or None,
        skip_entrypoint_processing=True,
    )


def _convert_tools(raw) -> list:
    """Convert native Tools/toolkits to agno Functions; pass agno objects through."""
    result = []
    for t in raw or []:
        if isinstance(t, Tool):
            result.append(_to_agno_function(t))
        elif hasattr(t, "functions") and isinstance(t.functions, dict):
            result.extend(_to_agno_function(f) for f in t.functions.values())
        else:
            result.append(t)
    return result


def _wrap_tools(tools):
    """Wrap a tools list or callable factory so native Tools are converted."""
    if callable(tools) and not isinstance(tools, (list, tuple)):

        def factory(run_context=None, **kwargs):
            raw = tools(run_context) if run_context is not None else tools()
            return _convert_tools(raw)

        return factory
    return _convert_tools(tools)


class AgnoAgentAdapter:
    """Adapts an Agno Agent to the Semente ``Agent`` protocol."""

    def __init__(self, agent: AgnoAgent):
        self.agent = agent

    def run(self, input: AgentInput) -> AgentTurn:
        response = self.agent.run(
            input.text,
            images=[to_engine_media(i, EImage) for i in input.images] if input.images else None,
            audio=[to_engine_media(a, EAudio) for a in input.audio] if input.audio else None,
            files=[to_engine_media(f, EFile) for f in input.files] if input.files else None,
            user_id=input.user_id,
            session_state=input.session_state,
        )

        content = response.content
        structured = None
        if content is not None and not isinstance(content, str):
            structured = content.model_dump() if hasattr(content, "model_dump") else content
            content = ""

        return AgentTurn(
            content=content or "",
            structured=structured,
            images=response.images,
            videos=response.videos,
            audio=response.audio,
            files=response.files,
            metrics=response.metrics,
        )


class AgnoBackend(EngineBackend):
    name = "agno"

    def build_agent(self, spec: AgentSpec) -> Agent:
        agent = AgnoAgent(
            name=spec.name,
            tools=_wrap_tools(spec.tools),
            markdown=True,
            use_instruction_tags=False,
            instructions=spec.instructions,
            cache_callables=False,
            output_schema=spec.output_schema,
            use_json_mode=spec.output_schema is not None,
            knowledge=spec.knowledge,
            search_knowledge=spec.knowledge is not None,
            add_search_knowledge_instructions=spec.knowledge is not None,
            model=_build_model(spec.model),
            add_datetime_to_context=True,
            timezone_identifier="America/Sao_Paulo",
            debug_mode=config.DEBUG_MODE,
        )
        return AgnoAgentAdapter(agent)

    def supports(self, capability: str) -> bool:
        return capability in {"structured_output", "multimodal_in", "media_out"}
