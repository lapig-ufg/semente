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
from semente.tools import Calculator, Tool, ToolResult, tool


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
    print("Native tool layer + skills tests OK")
