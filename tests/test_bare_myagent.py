"""MyAgent + GeminiProvider tests — mocked genai client, no network.

Covers the tool loop end to end with real genai types (Content/Part/
FunctionCall/FunctionResponse): provider wire shape, the call -> execute ->
respond -> answer round-trips, media stashing, dynamic tools, and
BareBackend's MyAgent-vs-tool-loop routing.
"""

from unittest.mock import MagicMock, patch

from google.genai.types import (
    Candidate,
    Content,
    FunctionCall,
    FunctionResponse,
    GenerateContentResponse,
    Part,
)

from semente.backends.base import AgentInput, AgentSpec, ModelSpec
from semente.backends.bare import BareBackend, MyAgent
from semente.backends.bare.providers import GeminiProvider, Provider
from semente.backends.bare.providers.base import GenerateResult, ToolCall
from semente.configs.config import config
from semente.tools import tool
from semente.tools.types import Image, ToolResult


class _FakeProvider(Provider):
    name = "fake"

    def __init__(self, results):
        self.results = iter(results)
        self.calls = []

    def generate(self, system, message=None, model_id=None, tools=None, history=None):
        self.calls.append(
            {"system": system, "message": message, "model_id": model_id, "tools": tools or [], "history": history}
        )
        result = next(self.results)
        if isinstance(result, str):
            return GenerateResult(text=result)
        return result

    def user_turn(self, message):
        return {"role": "user", "content": message}

    def tool_results_turn(self, outputs):
        return [{"role": "tool", "outputs": outputs}]


def _model_response(parts) -> GenerateContentResponse:
    return GenerateContentResponse(
        candidates=[Candidate(content=Content(role="model", parts=parts))]
    )


def _function_call_response(call_id, name, args) -> GenerateContentResponse:
    return _model_response([Part(function_call=FunctionCall(id=call_id, name=name, args=args))])


def _text_response(text) -> GenerateContentResponse:
    return _model_response([Part(text=text)])


def _make_map_tool():
    @tool(description="make a map")
    def make_map(run_context, feature_id: str) -> ToolResult:
        return ToolResult(
            content=f"map for {feature_id}",
            images=[Image(content=b"X", mime_type="image/png")],
        )

    return make_map


def _fake_client(responses):
    fake = MagicMock()
    fake.models.generate_content.side_effect = lambda **kw: next(responses)
    return fake


def test_myagent_chat_returns_reply():
    provider = _FakeProvider(["hello back"])
    agent = MyAgent(instructions="be nice", provider=provider)
    assert agent.chat("hi") == "hello back"
    assert provider.calls[0]["message"] == "hi"
    assert provider.calls[0]["system"] == "be nice"


def test_myagent_defaults_to_gemini_provider():
    agent = MyAgent(instructions="be nice")  # dummy key from conftest
    assert isinstance(agent.provider, GeminiProvider)
    assert agent.model_id == config.PRIMARY_MODEL_ID


def test_gemini_generate_sends_system_instruction():
    from google.genai.types import GenerateContentConfig

    provider = GeminiProvider()
    fake = _fake_client(iter([_text_response("gemini says hi")]))
    provider._client = fake

    out = provider.generate(system="be nice", message="hi", model_id="gemini-3.5-flash-lite")

    assert isinstance(out.text, str) and out.text == "gemini says hi"
    fake.models.generate_content.assert_called_once_with(
        model="gemini-3.5-flash-lite",
        contents=[Content(role="user", parts=[Part(text="hi")])],
        config=GenerateContentConfig(system_instruction="be nice"),
    )


def test_gemini_generate_uses_default_model():
    provider = GeminiProvider()
    fake = _fake_client(iter([_text_response("ok")]))
    provider._client = fake

    provider.generate(system="s", message="m")

    assert fake.models.generate_content.call_args.kwargs["model"] == provider.default_model


def test_gemini_generate_without_system_passes_none_config():
    provider = GeminiProvider()
    fake = _fake_client(iter([_text_response("ok")]))
    provider._client = fake

    provider.generate(system="", message="hi", model_id="m")

    fake.models.generate_content.assert_called_once_with(
        model="m", contents=[Content(role="user", parts=[Part(text="hi")])], config=None
    )


def test_gemini_generate_sends_typed_tool_declarations():
    from google.genai.types import GenerateContentConfig
    from google.genai.types import Tool as GenaiTool

    provider = GeminiProvider()
    fake = _fake_client(iter([_text_response("ok")]))
    provider._client = fake

    provider.generate(system="s", message="hi", tools=[_make_map_tool()])

    config_used = fake.models.generate_content.call_args.kwargs["config"]
    assert isinstance(config_used, GenerateContentConfig)
    assert isinstance(config_used.tools[0], GenaiTool)
    decl = config_used.tools[0].function_declarations[0]
    assert decl.name == "make_map"
    assert decl.parameters_json_schema["properties"] == {"feature_id": {"type": "string"}}


def test_gemini_parse_extracts_tool_calls():
    provider = GeminiProvider()
    fake = _fake_client(
        iter([_function_call_response("call-1", "make_map", {"feature_id": "f1"})])
    )
    provider._client = fake

    out = provider.generate(system="s", message="draw f1")

    assert out.text == ""
    assert len(out.tool_calls) == 1
    assert out.tool_calls[0] == ToolCall(id="call-1", name="make_map", args={"feature_id": "f1"})
    assert out.turn is not None


def test_gemini_tool_results_turn_builds_typed_parts():
    provider = GeminiProvider()
    turns = provider.tool_results_turn(
        [(ToolCall(id="call-1", name="make_map", args={}), "map for f1")]
    )

    assert len(turns) == 1
    content = turns[0]
    assert isinstance(content, Content)
    assert content.role == "user"
    fr = content.parts[0].function_response
    assert isinstance(fr, FunctionResponse)
    assert fr.id == "call-1"
    assert fr.name == "make_map"
    assert fr.response == {"result": "map for f1"}


def test_myagent_tool_loop_calls_executes_and_answers():
    provider = _FakeProvider(
        [
            GenerateResult(
                tool_calls=[ToolCall(id="call-1", name="make_map", args={"feature_id": "f1"})],
                turn="model-turn",
            ),
            GenerateResult(text="Here is your map."),
        ]
    )
    agent = MyAgent(instructions="be nice", provider=provider, tools=[_make_map_tool()])

    assert agent.chat("draw f1") == "Here is your map."

    # Round 1: fresh message, no history.
    assert provider.calls[0]["message"] == "draw f1"
    assert provider.calls[0]["history"] is None
    # Round 2: no new message; history = user turn + model turn + tool results.
    second = provider.calls[1]
    assert second["message"] is None
    assert second["history"][0] == {"role": "user", "content": "draw f1"}
    assert second["history"][1] == "model-turn"
    outputs = second["history"][2]["outputs"]
    assert len(outputs) == 1
    call, output = outputs[0]
    assert call.name == "make_map"
    assert output == "map for f1"


def test_myagent_run_surfaces_media_from_tool():
    provider = _FakeProvider(
        [
            GenerateResult(
                tool_calls=[ToolCall(id=None, name="make_map", args={"feature_id": "f1"})],
                turn="model-turn",
            ),
            GenerateResult(text="done"),
        ]
    )
    agent = MyAgent(instructions="be nice", provider=provider, tools=[_make_map_tool()])
    turn = agent.run(AgentInput(text="draw f1", session_state={}, user_id="u1"))

    assert turn.content == "done"
    assert len(turn.images) == 1
    assert turn.images[0].mime_type == "image/png"


def test_myagent_dynamic_tools_resolve_against_session_state():
    provider = _FakeProvider([GenerateResult(text="no tools"), GenerateResult(text="with tools")])
    dynamic = lambda ctx: [t for t in [_make_map_tool()] if ctx.session_state.get("maps", False)]
    agent = MyAgent(instructions="be nice", provider=provider, tools=dynamic)

    agent.chat("hi", session_state={"maps": False})
    assert provider.calls[0]["tools"] == []

    agent.chat("draw", session_state={"maps": True})
    assert [t.name for t in provider.calls[1]["tools"]] == ["make_map"]


def test_myagent_unknown_tool_feeds_back_error_text():
    provider = _FakeProvider(
        [
            GenerateResult(
                tool_calls=[ToolCall(id="x", name="nope", args={})],
                turn="model-turn",
            ),
            GenerateResult(text="recovered"),
        ]
    )
    agent = MyAgent(instructions="be nice", provider=provider, tools=[_make_map_tool()])

    assert agent.chat("hi") == "recovered"
    outputs = provider.calls[1]["history"][2]["outputs"]
    assert outputs[0][1] == "Unknown tool: nope"


def test_from_spec_static_and_callable_instructions():
    spec = AgentSpec(name="t", instructions="be nice", tools=[_make_map_tool()])
    agent = MyAgent.from_spec(spec)
    assert agent._system(None) == "be nice"
    assert [t.name for t in agent._resolve_tools(None)] == ["make_map"]

    spec = AgentSpec(name="t", instructions=lambda ctx: f"hello {ctx.user_id}")
    agent = MyAgent.from_spec(spec)
    assert agent._system(type("C", (), {"user_id": "u1", "session_state": {}})()) == "hello u1"


def test_backend_routes_chat_and_tool_specs_to_myagent():
    backend = BareBackend()
    for spec in [
        AgentSpec(name="t", instructions="be nice"),
        AgentSpec(name="t", instructions="be nice", tools=[_make_map_tool()]),
    ]:
        assert isinstance(backend.build_agent(spec), MyAgent)


def test_backend_routes_rich_specs_to_tool_loop():
    backend = BareBackend()
    rich = [
        AgentSpec(name="t", instructions="s", output_schema=dict),
        AgentSpec(name="t", instructions="s", multimodal_in=True),
        AgentSpec(name="t", instructions="s", knowledge=object()),
        AgentSpec(name="t", instructions="s", model=ModelSpec(provider="ollama", model_id="m")),
    ]
    for spec in rich:
        assert not isinstance(backend.build_agent(spec), MyAgent), spec


def test_gemini_missing_key_raises():
    with patch.object(config, "GOOGLE_API_KEY", None):
        try:
            GeminiProvider()
        except ValueError as e:
            assert "GOOGLE_API_KEY" in str(e)
        else:
            raise AssertionError("expected ValueError for missing GOOGLE_API_KEY")


if __name__ == "__main__":
    test_myagent_chat_returns_reply()
    test_myagent_defaults_to_gemini_provider()
    test_gemini_generate_sends_system_instruction()
    test_gemini_generate_uses_default_model()
    test_gemini_generate_without_system_passes_none_config()
    test_gemini_generate_sends_typed_tool_declarations()
    test_gemini_parse_extracts_tool_calls()
    test_gemini_tool_results_turn_builds_typed_parts()
    test_myagent_tool_loop_calls_executes_and_answers()
    test_myagent_run_surfaces_media_from_tool()
    test_myagent_dynamic_tools_resolve_against_session_state()
    test_myagent_unknown_tool_feeds_back_error_text()
    test_from_spec_static_and_callable_instructions()
    test_backend_routes_chat_and_tool_specs_to_myagent()
    test_backend_routes_rich_specs_to_tool_loop()
    test_gemini_missing_key_raises()
    print("MyAgent tests OK")