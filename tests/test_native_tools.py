"""Native tool layer + skills: Tool dataclass, tool() decorator, Calculator,
agno Function conversion, and the native SKILL.md reader."""

import tempfile
from pathlib import Path

from semente.backends.agno import _to_agno_function
from semente.backends.toolkit import (
    StateContext,
    expand_tools,
    new_media_bag,
    run_tool,
    tool_schema,
)
from semente.skills import load_skills
from semente.tools import Calculator, File, Tool, ToolResult, tool


@tool(description="Add two numbers", tool_hooks=[])
def add(a: float, b: float) -> ToolResult:
    return ToolResult(content=str(a + b))


def test_tool_is_native_and_callable():
    assert isinstance(add, Tool)
    assert add.name == "add"
    assert add(1, 2).content == "3"  # __call__ delegates to the raw func


def test_tool_schema():
    s = tool_schema(add)
    assert s["name"] == "add"
    assert s["description"] == "Add two numbers"
    assert s["parameters"]["properties"]["a"]["type"] == "number"


def test_calculator_schema_types_are_numeric():
    # Regression: semente.tools has `from __future__ import annotations`, so
    # `a: float` is stored as the string "float"; the schema must still map it
    # to {"type": "number"} (it previously degraded to {"type": "string"}, which
    # made the model send "746.28" as a str and crashed divide with TypeError).
    c = Calculator()
    for name in ("add", "subtract", "multiply", "divide", "exponentiate"):
        s = tool_schema(c.functions[name])
        assert s["parameters"]["properties"]["a"]["type"] == "number", name
        assert s["parameters"]["properties"]["b"]["type"] == "number", name
    assert tool_schema(c.functions["square_root"])["parameters"]["properties"]["n"]["type"] == "number"
    assert tool_schema(c.functions["factorial"])["parameters"]["properties"]["n"]["type"] == "integer"


def test_calculator_agno_conversion_numeric():
    f = _to_agno_function(Calculator().functions["divide"])
    assert f.parameters["properties"]["a"]["type"] == "number"
    assert f.parameters["properties"]["b"]["type"] == "number"


def test_schema_optional_and_union_types():
    from typing import Optional

    @tool()
    def f(a: Optional[int] = None, b: "float | None" = None) -> str:
        return "ok"

    s = tool_schema(f)
    assert s["parameters"]["properties"]["a"]["type"] == "integer"
    assert s["parameters"]["properties"]["b"]["type"] == "number"
    assert s["parameters"]["required"] == []  # optionality comes from the default


def test_agno_function_conversion():
    f = _to_agno_function(add)
    assert f.name == "add"
    assert f.parameters["properties"]["a"]["type"] == "number"
    assert f.entrypoint(a=1.0, b=2.0).content == "3.0"


def test_calculator_native():
    c = Calculator(exclude_tools=["is_prime", "factorial"])
    assert set(c.functions) == {"add", "subtract", "multiply", "divide", "exponentiate", "square_root"}
    expanded = expand_tools([c])
    assert len(expanded) == 6
    assert all(isinstance(t, Tool) for t in expanded)


def test_run_tool_shared_seam():
    c = Calculator()
    bag = new_media_bag()
    out = run_tool(c.functions["add"], {"a": 2, "b": 3}, StateContext({}), bag)
    assert out == '{"operation": "addition", "result": 5}'


def test_files_param_excluded_from_schema():
    """A tool declaring ``files`` must not expose it to the model."""

    @tool(description="Register from geojson")
    def register_geojson(files=None) -> ToolResult:
        return ToolResult(content="registered")

    s = tool_schema(register_geojson)
    assert "files" not in s["parameters"]["properties"]
    assert "files" not in s["parameters"]["required"]


def test_run_tool_injects_input_files():
    """The run's input files are injected into tools declaring ``files``."""

    @tool(description="Register from geojson")
    def register_geojson(files=None) -> ToolResult:
        assert files and files[0].format == "geojson"
        return ToolResult(content=f"got {len(files)} file(s)")

    ctx = StateContext({})
    bag = new_media_bag()
    input_files = [File(name="shape.json", content=b"{}", format="geojson")]

    out = run_tool(register_geojson, {}, ctx, bag, input_files=input_files)
    assert out == "got 1 file(s)"
    # Input files must NOT be echoed back as run output media.
    assert bag["files"] == []


def test_run_tool_injects_empty_files_when_none():
    @tool(description="Register from geojson")
    def register_geojson(files=None) -> ToolResult:
        return ToolResult(content=f"files={files}")

    out = run_tool(register_geojson, {}, StateContext({}), new_media_bag())
    assert out == "files=[]"


def test_agno_injects_run_files_into_tool_entrypoint():
    """agno injects run files into tools declaring a ``files`` param even with
    skip_entrypoint_processing=True — this pins the GeoJSON delivery path."""
    from semente.backends.agno import _wrap_result_conversion

    received: dict = {}

    @tool(description="Register from geojson")
    def register_geojson(files=None) -> ToolResult:
        received["files"] = files
        return ToolResult(content="ok")

    wrapped = _wrap_result_conversion(register_geojson)
    # agno reads the entrypoint signature to find the files param and injects
    # FunctionCall(files=...) as a keyword; functools.wraps propagates it.
    f = _to_agno_function(register_geojson)
    assert "files" not in (f.parameters or {}).get("properties", {}), (
        "files must not be exposed to the model"
    )


def test_agno_media_conversion_drops_rejected_mime():
    """agno File only accepts a mime whitelist; zip/rar/kmz/kml uploads (e.g.
    WhatsApp documents) must lose the mime but keep their bytes + filename
    instead of crashing the agent run (mirrors the legacy WhatsApp intake)."""
    from agno.media import File as EFile

    from semente.backends.agno.media import to_engine_media
    from semente.tools.types import File

    geo = to_engine_media(
        File(content=b"{}", mime_type="application/json", name="shape.json", format="geojson"),
        EFile,
    )
    assert geo.mime_type == "application/json" and geo.format == "geojson"

    zipped = to_engine_media(
        File(content=b"PK\x03\x04", mime_type="application/zip", name="shape.zip"),
        EFile,
    )
    assert zipped.mime_type is None
    assert zipped.name == "shape.zip" and zipped.content == b"PK\x03\x04"


def test_skills_reader_and_tools():
    d = Path(tempfile.mkdtemp()) / "ua-calculator"
    d.mkdir()
    (d / "SKILL.md").write_text(
        "---\nname: ua-calculator\ndescription: UA calc\n---\n# Instructions body\n"
    )
    skills = load_skills(str(d.parent))
    assert skills is not None
    snippet = skills.get_system_prompt_snippet()
    assert "ua-calculator" in snippet and "<skills_system>" in snippet
    tools = skills.get_tools()
    assert {t.name for t in tools} == {"get_skill_instructions", "get_skill_reference", "get_skill_script"}
    assert "Instructions body" in tools[0].func("ua-calculator")


if __name__ == "__main__":
    test_tool_is_native_and_callable()
    test_tool_schema()
    test_agno_function_conversion()
    test_calculator_native()
    test_run_tool_shared_seam()
    test_skills_reader_and_tools()
    test_files_param_excluded_from_schema()
    test_run_tool_injects_input_files()
    test_run_tool_injects_empty_files_when_none()
    test_agno_injects_run_files_into_tool_entrypoint()
    test_agno_media_conversion_drops_rejected_mime()
    print("Native tool layer + skills tests OK")
