"""Bare backend tests — mocked litellm, no network.

Covers the function-calling loop: tool schema extraction, tool execution with
media stashing, and the multi-turn tool-call -> final-answer flow.
"""

import json
from unittest.mock import patch

from semente.backends.base import AgentInput, AgentSpec
from semente.backends.bare.tool_loop import BareAgentAdapter
from semente.tools import tool
from semente.tools.types import Image, ToolResult


class _FakeToolCall:
    def __init__(self, id, name, arguments):
        self.id = id
        self.function = type("F", (), {"name": name, "arguments": arguments})()


class _FakeMessage:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls


class _FakeResponse:
    def __init__(self, message):
        self.choices = [type("C", (), {"message": message})()]


def _make_map_tool():
    @tool(description="make a map")
    def make_map(run_context, feature_id: str) -> ToolResult:
        return ToolResult(
            content=f"map for {feature_id}",
            images=[Image(content=b"X", mime_type="image/png")],
        )

    return make_map


def test_bare_loop_tool_call_then_answer():
    import litellm

    responses = iter(
        [
            _FakeResponse(
                _FakeMessage(
                    tool_calls=[
                        _FakeToolCall("call-1", "make_map", json.dumps({"feature_id": "f1"}))
                    ]
                )
            ),
            _FakeResponse(_FakeMessage(content="Here is your map.")),
        ]
    )
    with patch.object(litellm, "completion", lambda **kw: next(responses)):
        spec = AgentSpec(
            name="t",
            instructions=lambda ctx: "be helpful",
            tools=[_make_map_tool()],
        )
        turn = BareAgentAdapter(spec).run(AgentInput(text="draw f1", session_state={}))

    assert turn.content == "Here is your map."
    assert len(turn.images) == 1
    assert turn.images[0].mime_type == "image/png"


def test_bare_loop_plain_answer():
    import litellm

    with patch.object(
        litellm, "completion", lambda **kw: _FakeResponse(_FakeMessage(content="hello"))
    ):
        spec = AgentSpec(name="t", instructions=lambda ctx: "be helpful", tools=[])
        turn = BareAgentAdapter(spec).run(AgentInput(text="hi", session_state={}))

    assert turn.content == "hello"
    assert turn.images is None


if __name__ == "__main__":
    test_bare_loop_tool_call_then_answer()
    test_bare_loop_plain_answer()
    print("Bare backend tests OK")
