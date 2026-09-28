"""Engine-neutral tool execution — shared by the ADK and bare backends.

Every non-Agno engine needs the same tool seam: unwrap agno Functions, expand
toolkits, run the hook chain, stash media in a per-run bag, and produce the
OpenAI-style schema the model sees. Agno does all of this natively; ADK and
the bare backend share this module.
"""

from __future__ import annotations

import inspect
import json
import types
import typing
from typing import Any

from semente.tools.types import Tool, ToolResult


class StateContext:
    """Minimal Context for resolving dynamic tools/instructions against a state dict."""

    def __init__(self, session_state: dict, user_id: str | None = None):
        self.session_state = session_state
        self.user_id = user_id
        self.messages = None


def unwrap(func):
    # Native Tool -> raw func.
    if isinstance(func, Tool):
        return func.func
    # agno Function wraps the entrypoint; semente.tool wraps the original func.
    if hasattr(func, "entrypoint"):
        func = func.entrypoint
    while hasattr(func, "__wrapped__"):
        func = func.__wrapped__
    return func


def expand_tools(tools: list) -> list:
    """Expand agno toolkits (e.g. Calculator) into their member functions."""
    expanded = []
    for t in tools:
        functions = getattr(t, "functions", None)
        if isinstance(functions, dict):
            expanded.extend(functions.values())
        else:
            expanded.append(t)
    return expanded


def new_media_bag() -> dict:
    return {"images": [], "videos": [], "audios": [], "files": []}


def new_input_files_bag() -> list:
    """Per-run bag of files attached to the run input (e.g. GeoJSON converted
    by the input step). Injected into tools declaring a ``files`` parameter;
    kept separate from ``media_bag`` so input files are not echoed back as
    run output."""
    return []


def result_to_str(result, media_bag: dict) -> str:
    """Convert a tool result to the text the engine feeds back to the LLM,
    stashing any media artifacts in the per-run bag (media never enters the loop)."""
    if isinstance(result, ToolResult):
        if result.images:
            media_bag["images"].extend(result.images)
        if result.videos:
            media_bag["videos"].extend(result.videos)
        if result.audios:
            media_bag["audios"].extend(result.audios)
        if result.files:
            media_bag["files"].extend(result.files)
        return result.content
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        return json.dumps(result, default=str)
    return str(result)


def bind_args(sig, args, kwargs) -> dict:
    bound = sig.bind(*args, **kwargs)
    bound.apply_defaults()
    return dict(bound.arguments)


def build_hook_chain(func, hooks, has_run_context):
    """Replicate agno's nested tool_hooks chain (middleware semantics).

    Innermost calls the raw function; each hook wraps the next and may either
    call ``function_call(**arguments)`` to continue the chain or return a value
    to short-circuit. Mirrors agno.tools.function._build_nested_execution_chain.
    """

    def entrypoint(args, ctx):
        if has_run_context:
            return func(**args, run_context=ctx)
        return func(**args)

    chain = entrypoint
    for hook in reversed(hooks):

        def make_wrapper(inner, hook):
            def wrapper(args, ctx):
                def next_func(**kwargs):
                    return inner(kwargs, ctx)

                # The rate-limit hook keys its cache on function_call.__name__.
                next_func.__name__ = getattr(func, "__name__", "tool")
                return hook(run_context=ctx, function_call=next_func, arguments=args)

            return wrapper

        chain = make_wrapper(chain, hook)
    return chain


# Framework-managed parameters: never exposed to the model; injected at
# call time by the backend (mirrors agno's handling of ``files``).
_MANAGED_PARAMS = ("run_context", "files")


def run_tool(tool, args: dict, ctx, media_bag: dict, input_files: list | None = None) -> str:
    """Execute one tool: hook chain + raw func; media stashed, text returned.

    ``input_files`` (the run's attached files) is injected into any tool
    declaring a ``files`` parameter, mirroring agno's framework injection.
    """
    func = unwrap(tool)
    sig = inspect.signature(func)
    has_run_context = "run_context" in sig.parameters
    wants_files = "files" in sig.parameters
    hooks = getattr(tool, "tool_hooks", None) or []
    chain = build_hook_chain(func, hooks, has_run_context)
    if wants_files:
        args = {**args, "files": list(input_files or [])}
    return result_to_str(chain(args, ctx), media_bag)


def tool_schema(tool) -> dict:
    """OpenAI-style function schema (name/description/parameters) for one tool."""
    if isinstance(tool, Tool):
        func = tool.func
        name = tool.name
        description = tool.description
    else:
        if hasattr(tool, "to_dict"):
            d = tool.to_dict()
            if isinstance(d, dict):
                return d
        func = unwrap(tool)
        name = getattr(func, "__name__", "tool")
        description = (inspect.getdoc(func) or "").strip()
    sig = inspect.signature(func)
    # Resolve PEP 563 string annotations (``from __future__ import annotations``
    # stores ``a: float`` as the string "float") and forward references; fall
    # back to the raw annotation when resolution fails.
    try:
        type_hints = typing.get_type_hints(func)
    except Exception:
        type_hints = {}
    properties: dict = {}
    required: list = []
    for pname, p in sig.parameters.items():
        if pname in _MANAGED_PARAMS:
            continue
        properties[pname] = _py_type_to_json(type_hints.get(pname, p.annotation))
        if p.default is inspect.Parameter.empty:
            required.append(pname)
    return {
        "name": name,
        "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required},
    }


_STRING_ANNOTATIONS = {
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "list": list,
    "dict": dict,
    "None": type(None),
    "NoneType": type(None),
}


def _py_type_to_json(annotation) -> dict:
    """Map a Python type annotation to a JSON-schema fragment (dict).

    Handles PEP 563 string annotations and ``Optional``/``Union``/``X | None``
    (the latter resolve to the non-None member; optionality is expressed by the
    ``required`` list, not the schema type).
    """
    if annotation is inspect.Parameter.empty:
        return {"type": "string"}

    # PEP 563 string annotation (e.g. "float") — best-effort by builtin name.
    if isinstance(annotation, str):
        return _py_type_to_json(_STRING_ANNOTATIONS.get(annotation.strip(), str))

    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)

    # Optional[X] / X | None -> X; other unions fall back to string.
    if origin in (typing.Union, types.UnionType):
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            return _py_type_to_json(non_none[0])
        return {"type": "string"}

    if annotation is str or origin is str:
        return {"type": "string"}
    if annotation is bool or origin is bool:
        return {"type": "boolean"}
    if annotation is int or origin is int:
        return {"type": "integer"}
    if annotation is float or origin is float:
        return {"type": "number"}
    if annotation is list or origin is list:
        item = args[0] if args else str
        return {"type": "array", "items": _py_type_to_json(item)}
    if annotation is dict or origin is dict:
        return {"type": "object"}
    return {"type": "string"}
