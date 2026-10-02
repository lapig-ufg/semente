"""MyAgent — an agent built from scratch on the provider port.

Holds an instruction, tools, and a provider. ``chat`` drives the tool loop:
one provider round-trip, execute any tool calls (engine-neutral, via
``backends/toolkit.py`` — hooks, ``run_context``/``files`` injection, media
bag), feed results back, repeat until text or the iteration cap. Stateless
by design (no history between runs) — sessions belong to whoever drives the
agent.

``from_spec``/``run`` make it speak the framework's ``Agent`` protocol, so
``BareBackend`` routes every spec here. Structured output, multimodal input,
and knowledge are planned next (DECISIONS.md).

Event system (``events.py``): ``subscribe(AgentEvents.X, handler)`` hooks
run boundaries (``AGENT_START``/``AGENT_END``) and each tool execution
(``TOOL_EXECUTION_START``/``TOOL_EXECUTION_END``). Handlers get one mutable
event object — observe fields, or assign them to customize: on
``TOOL_EXECUTION_START`` the agent executes whatever ``tool_name``/``args``
the event carries after all handlers ran (mutations never touch the provider
wire — the model's own call is echoed back verbatim).
"""

from __future__ import annotations

from typing import Callable

from semente.backends.base import AgentInput, AgentSpec, AgentTurn
from semente.backends.bare.events import (
    AgentEndEvent,
    AgentEvents,
    AgentMessage,
    AgentStartEvent,
    EventBus,
    ToolExecutionEndEvent,
    ToolExecutionStartEvent,
)
from semente.backends.bare.metrics import AgentMetrics
from semente.backends.bare.providers import GenerateResult, GeminiProvider, Provider, ToolCall
from semente.backends.toolkit import StateContext, expand_tools, new_media_bag, run_tool
from semente.tools.types import Tool

_MAX_TOOL_ITERATIONS = 10  # ponytail: cap the loop; raise if a domain needs more


class MyAgent:
    """One system instruction + tools + one provider = one tool loop."""

    def __init__(
        self,
        instructions: str | Callable[..., str],
        provider: Provider | None = None,
        model_id: str | None = None,
        tools: list[Tool] | Callable[[StateContext], list[Tool]] | None = None,
        events: EventBus | None = None,
    ):
        self.instructions = instructions
        self.provider = provider or GeminiProvider(model_id=model_id)
        self.model_id = model_id or getattr(self.provider, "default_model", None)
        self.tools = tools
        self.events = events or EventBus()

    def subscribe(self, event: AgentEvents, handler: Callable) -> None:
        """Observe or customize runs — see ``events.py`` for payloads."""
        self.events.subscribe(event, handler)

    def _resolve_instructions(self, ctx: StateContext) -> str:
        if callable(self.instructions):
            try:
                return self.instructions(ctx)
            except TypeError:
                return self.instructions()
        return self.instructions

    def _resolve_tools(self, ctx: StateContext) -> list[Tool]:
        """Static list, or a callable resolved against the run's state."""
        if self.tools is None:
            return []
        if callable(self.tools) and not isinstance(self.tools, list):
            try:
                raw = self.tools(ctx)
            except TypeError:
                raw = self.tools()
        else:
            raw = self.tools or []
        return expand_tools(list(raw))

    def _execute(self, message: str, ctx: StateContext, media_bag: dict) -> tuple[str, AgentMetrics]:
        """Run the tool loop; media artifacts land in ``media_bag``.

        One flat loop: generate over the accumulated history, break when the
        model answers without tool calls, otherwise execute the calls, feed
        the results back, and generate again — capped at
        ``_MAX_TOOL_ITERATIONS`` provider rounds. The cap round's calls are
        NOT executed (their results could never be fed back — running them
        would be wasted side effects); the last text is returned with a
        warning. Emits ``AGENT_START`` on entry, per-tool execution events
        around each tool, and ``AGENT_END`` with the neutral message log on
        completion (no ``AGENT_END`` when the provider or a tool raises —
        the run itself failed; handler exceptions are swallowed by the bus).

        Returns ``(text, metrics)``: the run's ``AgentMetrics`` — every
        round and tool execution recorded as they happen (token counts are
        cumulative wire usage, last round wins; timings via ``perf_counter``).
        """
        from time import perf_counter

        metrics = AgentMetrics.start(self.provider.name, self.model_id)
        self.events.emit(AgentEvents.AGENT_START, AgentStartEvent(session_state=ctx.session_state))
        messages: list[AgentMessage] = [AgentMessage(role="user", content=message)]

        system = self._resolve_instructions(ctx)
        resolved = self._resolve_tools(ctx)

        history: list = [self.provider.user_turn(message)]
        for round_no in range(_MAX_TOOL_ITERATIONS):
            round_start = perf_counter()
            result = self.provider.generate(
                system, history=history, model_id=self.model_id, tools=resolved or None
            )
            metrics.record_round(usage=result.usage, round_duration=perf_counter() - round_start)
            if result.turn is not None:
                history.append(result.turn)

            if not result.tool_calls:
                break  # final answer

            if round_no == _MAX_TOOL_ITERATIONS - 1:
                from semente.logging import log_warning

                log_warning("tool loop hit the iteration cap; returning last text")
                break

            messages.extend(
                AgentMessage(
                    role="assistant",
                    tool_name=call.name,
                    tool_call_id=call.id,
                    args=dict(call.args),
                )
                for call in result.tool_calls
            )
            outputs = [
                (call, self._run_one(call, resolved, ctx, media_bag, messages, metrics))
                for call in result.tool_calls
            ]
            history.extend(self.provider.tool_results_turn(outputs))

        messages.append(AgentMessage(role="assistant", content=result.text))
        self.events.emit(AgentEvents.AGENT_END, AgentEndEvent(messages=messages))
        metrics.finish()
        return result.text, metrics

    def _run_one(
        self,
        call: ToolCall,
        tools: list[Tool],
        ctx: StateContext,
        media_bag: dict,
        messages: list[AgentMessage],
        metrics: AgentMetrics,
    ) -> str:
        """Resolve and execute one tool call, events around it.

        ``TOOL_EXECUTION_START`` fires before lookup: the agent executes the
        ``tool_name``/``args`` the event carries after all handlers ran
        (rename redirects to another tool; unknown name -> "Unknown tool").
        The provider echo (``outputs``) always pairs the ORIGINAL call —
        mutations never touch the wire. ``TOOL_EXECUTION_END`` fires with
        ``is_error`` for unknown tools and tool exceptions (then raised).
        Execution is timed into ``metrics`` (name, duration, is_error).
        """
        from time import perf_counter

        start = ToolExecutionStartEvent(
            tool_call_id=call.id, tool_name=call.name, args=dict(call.args)
        )
        self.events.emit(AgentEvents.TOOL_EXECUTION_START, start)

        executed = perf_counter()
        tool = next((t for t in tools if getattr(t, "name", None) == start.tool_name), None)
        if tool is None:
            metrics.record_tool(start.tool_name, perf_counter() - executed, is_error=True)
            end = ToolExecutionEndEvent(
                tool_call_id=call.id,
                tool_name=start.tool_name,
                result=f"Unknown tool: {start.tool_name}",
                is_error=True,
            )
            messages.append(AgentMessage(role="tool", content=end.result, tool_name=start.tool_name, tool_call_id=call.id))
            self.events.emit(AgentEvents.TOOL_EXECUTION_END, end)
            return end.result

        try:
            result = run_tool(tool, start.args, ctx, media_bag)
        except Exception as e:
            metrics.record_tool(start.tool_name, perf_counter() - executed, is_error=True)
            end = ToolExecutionEndEvent(
                tool_call_id=call.id, tool_name=start.tool_name, result=str(e), is_error=True
            )
            self.events.emit(AgentEvents.TOOL_EXECUTION_END, end)
            raise
        metrics.record_tool(start.tool_name, perf_counter() - executed, is_error=False)
        end = ToolExecutionEndEvent(
            tool_call_id=call.id, tool_name=start.tool_name, result=result, is_error=False
        )
        messages.append(
            AgentMessage(role="tool", content=result, tool_name=start.tool_name, tool_call_id=call.id)
        )
        self.events.emit(AgentEvents.TOOL_EXECUTION_END, end)
        return result

    def chat(self, message: str, session_state: dict | None = None, user_id: str | None = None) -> str:
        ctx = StateContext(session_state or {}, user_id)
        return self._execute(message, ctx, new_media_bag())[0]

    @classmethod
    def from_spec(cls, spec: AgentSpec) -> MyAgent:
        """Build from the engine-neutral ``AgentSpec``."""
        return cls(
            instructions=spec.instructions,
            model_id=spec.model.model_id if spec.model else None,
            tools=spec.tools or None,
        )

    def run(self, input: AgentInput) -> AgentTurn:
        """Framework run primitive: one message in, one turn (text + media + metrics) out."""
        ctx = StateContext(input.session_state or {}, input.user_id)
        media_bag = new_media_bag()
        text, metrics = self._execute(input.text or "", ctx, media_bag)
        return AgentTurn(
            content=text,
            images=media_bag["images"] or None,
            videos=media_bag["videos"] or None,
            audio=media_bag["audios"] or None,
            files=media_bag["files"] or None,
            metrics=metrics.to_dict(),
        )
