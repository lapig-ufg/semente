"""MyAgent event system tests — mocked provider, no network.

Covers the four events end to end: AGENT_START (session_state by reference),
AGENT_END (neutral message log), TOOL_EXECUTION_START (observation + arg/name
mutation redirecting execution), TOOL_EXECUTION_END (result / is_error), and
the bus contract: handlers in subscription order, chained mutations, and
swallow+log on handler exceptions.
"""

import pytest

from semente.backends.base import AgentInput
from semente.backends.bare.events import (
    AgentEndEvent,
    AgentEvents,
    AgentStartEvent,
    EventBus,
    ToolExecutionEndEvent,
    ToolExecutionStartEvent,
)
from semente.backends.bare.providers import GenerateResult, Provider
from semente.backends.bare.providers.base import ToolCall
from semente.backends.bare.agent import MyAgent
from semente.tools import tool
from semente.tools.types import ToolResult, Image


class _FakeProvider(Provider):
    name = "fake"

    def __init__(self, results):
        self.results = iter(results)
        self.echoed_outputs = []

    def generate(self, system, message=None, model_id=None, tools=None, history=None):
        result = next(self.results)
        return result if isinstance(result, GenerateResult) else GenerateResult(text=result)

    def user_turn(self, message):
        return {"role": "user", "content": message}

    def tool_results_turn(self, outputs):
        self.echoed_outputs.append(list(outputs))
        return [{"role": "tool", "outputs": outputs}]


def _tool_call(name, args, call_id="call-1"):
    return GenerateResult(tool_calls=[ToolCall(id=call_id, name=name, args=dict(args))])


def _map_tool():
    @tool(description="make a map")
    def make_map(run_context, feature_id: str) -> ToolResult:
        return ToolResult(
            content=f"map for {feature_id}",
            images=[Image(content=b"X", mime_type="image/png")],
        )

    return make_map


def _echo_tool():
    @tool(description="echo a value")
    def echo_value(run_context, value: str) -> ToolResult:
        return ToolResult(content=f"echo: {value}")

    return echo_value


def _failing_tool():
    @tool(description="always fails")
    def boom(run_context) -> ToolResult:
        raise RuntimeError("tool exploded")

    return boom


# ---- AGENT_START / AGENT_END -------------------------------------------------


def test_agent_start_sees_session_state_by_reference():
    state = {"k": "v"}
    seen = []
    agent = MyAgent(instructions="s", provider=_FakeProvider(["done"]))
    agent.subscribe(AgentEvents.AGENT_START, lambda e: seen.append(e))

    agent.chat("hi", session_state=state)

    assert isinstance(seen[0], AgentStartEvent)
    assert seen[0].session_state is state  # by reference — handlers can seed state
    assert seen[0].session_state["k"] == "v"


def test_agent_end_carries_neutral_message_log():
    provider = _FakeProvider([
        _tool_call("make_map", {"feature_id": "f1"}),
        GenerateResult(text="done"),
    ])
    agent = MyAgent(instructions="s", provider=provider, tools=[_map_tool()])
    ends = []
    agent.subscribe(AgentEvents.AGENT_END, lambda e: ends.append(e))

    text = agent.chat("draw f1", session_state={})

    assert text == "done"
    e = ends[0]
    assert isinstance(e, AgentEndEvent)
    roles = [(m.role, m.tool_name) for m in e.messages]
    assert roles == [
        ("user", None),
        ("assistant", "make_map"),
        ("tool", "make_map"),
        ("assistant", None),
    ]
    tool_msg = e.messages[2]
    assert tool_msg.tool_call_id == "call-1"
    assert tool_msg.content == "map for f1"
    request_msg = e.messages[1]
    assert request_msg.args == {"feature_id": "f1"}


def test_agent_end_fires_after_plain_chat_too():
    agent = MyAgent(instructions="s", provider=_FakeProvider(["hello"]))
    ends = []
    agent.subscribe(AgentEvents.AGENT_END, lambda e: ends.append(e))

    assert agent.chat("hi") == "hello"
    assert len(ends) == 1
    assert [(m.role, m.content) for m in ends[0].messages] == [("user", "hi"), ("assistant", "hello")]


def test_run_primitive_emits_events_like_chat():
    provider = _FakeProvider(["hello"])
    agent = MyAgent(instructions="s", provider=provider)
    starts, ends = [], []
    agent.subscribe(AgentEvents.AGENT_START, starts.append)
    agent.subscribe(AgentEvents.AGENT_END, ends.append)

    turn = agent.run(AgentInput(text="hi", session_state={"a": 1}))

    assert turn.content == "hello"
    assert starts[0].session_state == {"a": 1}
    assert len(ends) == 1


def test_no_agent_end_when_provider_raises():
    class _Boom(Provider):
        name = "boom"

        def generate(self, system, message=None, model_id=None, tools=None, history=None):
            raise RuntimeError("provider down")

    agent = MyAgent(instructions="s", provider=_Boom())
    ends = []
    agent.subscribe(AgentEvents.AGENT_END, lambda e: ends.append(e))

    with pytest.raises(RuntimeError):
        agent.chat("hi")
    assert ends == []


# ---- TOOL_EXECUTION_START: observation + customization ----------------------


def test_tool_start_observes_name_and_args():
    provider = _FakeProvider([
        _tool_call("make_map", {"feature_id": "f1"}),
        GenerateResult(tool_calls=[]),
    ])
    agent = MyAgent(instructions="s", provider=provider, tools=[_map_tool()])
    seen = []
    agent.subscribe(AgentEvents.TOOL_EXECUTION_START, lambda e: seen.append(e))

    agent.chat("draw f1")

    assert isinstance(seen[0], ToolExecutionStartEvent)
    assert seen[0].tool_call_id == "call-1"
    assert seen[0].tool_name == "make_map"
    assert seen[0].args == {"feature_id": "f1"}


def test_mutation_args_change_execution():
    provider = _FakeProvider([
        _tool_call("make_map", {"feature_id": "f1"}),
        GenerateResult(text="done"),
    ])
    agent = MyAgent(instructions="s", provider=provider, tools=[_map_tool()])
    agent.subscribe(
        AgentEvents.TOOL_EXECUTION_START, lambda e: e.args.update(feature_id="f2")
    )

    text = agent.chat("draw f1")

    assert text == "done"
    assert provider.echoed_outputs[0][0][1] == "map for f2"  # executed with the mutated args, fed back


def test_mutation_tool_name_redirects_execution():
    provider = _FakeProvider([
        _tool_call("make_map", {"feature_id": "f1"}),
        GenerateResult(text="done"),
    ])
    agent = MyAgent(
        instructions="s", provider=provider, tools=[_map_tool(), _echo_tool()]
    )

    def redirect(e):
        e.tool_name = "echo_value"  # redirect to another tool…
        e.args = {"value": "f1"}    # …whose signature the handler also fixes

    agent.subscribe(AgentEvents.TOOL_EXECUTION_START, redirect)

    agent.chat("draw f1")

    # echo_value executed with the redirected args
    assert provider.echoed_outputs[0][0][1] == "echo: f1"
    # wire invariant: the model's own call (name + id) is echoed back, not the mutation
    echoed_call = provider.echoed_outputs[0][0][0]
    assert (echoed_call.name, echoed_call.id) == ("make_map", "call-1")


def test_mutation_to_unknown_name_feeds_back_unknown_tool():
    provider = _FakeProvider([
        _tool_call("make_map", {"feature_id": "f1"}),
        GenerateResult(tool_calls=[]),
    ])
    agent = MyAgent(instructions="s", provider=provider, tools=[_map_tool()])
    ends = []
    agent.subscribe(AgentEvents.TOOL_EXECUTION_START, lambda e: setattr(e, "tool_name", "nope"))
    agent.subscribe(AgentEvents.TOOL_EXECUTION_END, ends.append)

    agent.chat("draw f1")

    assert ends[0].is_error is True
    assert provider.echoed_outputs[0][0][1] == "Unknown tool: nope"


def test_mutation_can_rescue_unknown_model_call():
    provider = _FakeProvider([
        _tool_call("does_not_exist", {"value": "x"}),
        GenerateResult(tool_calls=[]),
    ])
    agent = MyAgent(instructions="s", provider=provider, tools=[_echo_tool()])
    agent.subscribe(AgentEvents.TOOL_EXECUTION_START, lambda e: setattr(e, "tool_name", "echo_value"))

    agent.chat("hi")

    assert provider.echoed_outputs[0][0][1] == "echo: x"


# ---- TOOL_EXECUTION_END ------------------------------------------------------


def test_tool_end_carries_result_and_not_error():
    provider = _FakeProvider([
        _tool_call("make_map", {"feature_id": "f1"}),
        GenerateResult(tool_calls=[]),
    ])
    agent = MyAgent(instructions="s", provider=provider, tools=[_map_tool()])
    ends = []
    agent.subscribe(AgentEvents.TOOL_EXECUTION_END, ends.append)

    agent.chat("draw f1")

    e = ends[0]
    assert isinstance(e, ToolExecutionEndEvent)
    assert e.tool_name == "make_map"
    assert e.result == "map for f1"
    assert e.is_error is False


def test_tool_end_is_error_when_tool_raises_then_propagates():
    provider = _FakeProvider([
        _tool_call("boom", {}),
        GenerateResult(tool_calls=[]),
    ])
    agent = MyAgent(instructions="s", provider=provider, tools=[_failing_tool()])
    ends = []
    agent.subscribe(AgentEvents.TOOL_EXECUTION_END, ends.append)

    with pytest.raises(RuntimeError):
        agent.chat("hi")

    assert len(ends) == 1
    assert ends[0].is_error is True
    assert ends[0].result == "tool exploded"


def test_unknown_tool_without_mutation_is_error_end():
    provider = _FakeProvider([
        _tool_call("ghost", {}),
        GenerateResult(tool_calls=[]),
    ])
    agent = MyAgent(instructions="s", provider=provider)
    ends = []
    agent.subscribe(AgentEvents.TOOL_EXECUTION_END, ends.append)

    agent.chat("hi")  # unknown tools don't crash the run

    assert ends[0].is_error is True
    assert ends[0].tool_name == "ghost"


# ---- Bus contract ------------------------------------------------------------


def test_handlers_run_in_subscription_order_and_chain_mutations():
    bus = EventBus()
    seen = []
    bus.subscribe(
        AgentEvents.TOOL_EXECUTION_START, lambda e: seen.append(("first", dict(e.args)))
    )
    bus.subscribe(
        AgentEvents.TOOL_EXECUTION_START,
        lambda e: (e.args.update(x=2), seen.append(("second", dict(e.args)))),
    )

    bus.emit(AgentEvents.TOOL_EXECUTION_START, ToolExecutionStartEvent("id", "t", {"x": 1}))

    assert seen == [("first", {"x": 1}), ("second", {"x": 2})]  # second sees first's mutation


def test_handler_exception_swallowed_and_logged_rest_run():
    bus = EventBus()
    seen = []

    def boom(e):
        raise ValueError("handler bug")

    bus.subscribe(AgentEvents.AGENT_START, boom)
    bus.subscribe(AgentEvents.AGENT_START, lambda e: seen.append(e))

    bus.emit(AgentEvents.AGENT_START, AgentStartEvent(session_state={}))  # must not raise

    assert len(seen) == 1  # later handlers still ran


def test_handler_exception_does_not_break_the_run():
    provider = _FakeProvider(["hello"])
    agent = MyAgent(instructions="s", provider=provider)

    def boom(e):
        raise ValueError("observer bug")

    agent.subscribe(AgentEvents.AGENT_START, boom)

    assert agent.chat("hi") == "hello"


def test_multiple_tool_calls_emit_per_call_events():
    provider = _FakeProvider([
        GenerateResult(
            tool_calls=[
                ToolCall(id="c1", name="echo_value", args={"value": "a"}),
                ToolCall(id="c2", name="echo_value", args={"value": "b"}),
            ]
        ),
        GenerateResult(tool_calls=[]),
    ])
    agent = MyAgent(instructions="s", provider=provider, tools=[_echo_tool()])
    starts, ends = [], []
    agent.subscribe(AgentEvents.TOOL_EXECUTION_START, starts.append)
    agent.subscribe(AgentEvents.TOOL_EXECUTION_END, ends.append)

    agent.chat("hi")

    assert [e.tool_call_id for e in starts] == ["c1", "c2"]
    assert [e.result for e in ends] == ["echo: a", "echo: b"]


if __name__ == "__main__":
    test_agent_start_sees_session_state_by_reference()
    test_agent_end_carries_neutral_message_log()
    test_agent_end_fires_after_plain_chat_too()
    test_run_primitive_emits_events_like_chat()
    test_no_agent_end_when_provider_raises()
    test_tool_start_observes_name_and_args()
    test_mutation_args_change_execution()
    test_mutation_tool_name_redirects_execution()
    test_mutation_to_unknown_name_feeds_back_unknown_tool()
    test_mutation_can_rescue_unknown_model_call()
    test_tool_end_carries_result_and_not_error()
    test_tool_end_is_error_when_tool_raises_then_propagates()
    test_unknown_tool_without_mutation_is_error_end()
    test_handlers_run_in_subscription_order_and_chain_mutations()
    test_handler_exception_swallowed_and_logged_rest_run()
    test_handler_exception_does_not_break_the_run()
    test_multiple_tool_calls_emit_per_call_events()
    print("Event system tests OK")