"""Agent event system — observability + customization for ``MyAgent``.

Four events (``AgentEvents``) emitted at run boundaries and around each tool
execution. Subscribers receive ONE mutable event dataclass per emission:
observers read fields; customizers assign them. On
``TOOL_EXECUTION_START`` the agent executes whatever ``tool_name``/``args``
the event carries after all handlers ran — so a handler can change the args,
redirect to another tool, or rescue an unknown name into a real one.

Events fire per run of the loop (stateless agent — no history between runs).

``AGENT_END`` carries a neutral message log (``AgentMessage``), never the
provider-native history (decision D5): user message, assistant tool-call
requests, tool results, final answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class AgentEvents(Enum):
    """Events ``MyAgent`` emits during a run."""

    AGENT_START = "agent_start"
    AGENT_END = "agent_end"
    TOOL_EXECUTION_START = "tool_execution_start"
    TOOL_EXECUTION_END = "tool_execution_end"


@dataclass
class AgentMessage:
    """One entry of the neutral run trace attached to ``AGENT_END``.

    ``role`` is ``"user"`` | ``"assistant"`` | ``"tool"``. Assistant entries
    carry the tool call the model requested (``tool_name``, ``tool_call_id``,
    ``args``); tool entries carry the executed output.
    """

    role: str
    content: str = ""
    tool_name: str | None = None
    tool_call_id: str | None = None
    args: dict | None = None


@dataclass
class AgentStartEvent:
    """Emitted when a run starts — ``session_state`` by reference."""

    session_state: dict


@dataclass
class AgentEndEvent:
    """Emitted when a run completes — the neutral message log of the run."""

    messages: list[AgentMessage] = field(default_factory=list)


@dataclass
class ToolExecutionStartEvent:
    """Emitted before a tool executes — mutations drive execution.

    After all handlers run, the agent executes ``tool_name`` with ``args``
    as this event now carries them. The provider echo (what the model sees
    fed back) always uses the original call — mutations never touch the wire.
    """

    tool_call_id: str | None
    tool_name: str
    args: dict


@dataclass
class ToolExecutionEndEvent:
    """Emitted after a tool executes (or fails to resolve)."""

    tool_call_id: str | None
    tool_name: str
    result: Any
    is_error: bool


EventPayload = (
    AgentStartEvent
    | AgentEndEvent
    | ToolExecutionStartEvent
    | ToolExecutionEndEvent
)


class EventBus:
    """Per-agent pub/sub: handlers run in subscription order; mutations chain.

    A handler exception is swallowed and logged — an observer must never
    break a production run — and the remaining handlers still run.
    """

    def __init__(self):
        self._handlers: dict[AgentEvents, list[Callable]] = {}

    def subscribe(self, event: AgentEvents, handler: Callable) -> None:
        """Register ``handler`` for ``event``; it sees prior handlers' mutations."""
        self._handlers.setdefault(event, []).append(handler)

    def emit(self, event: AgentEvents, payload: EventPayload) -> None:
        """Invoke handlers in subscription order; swallow + log failures."""
        for handler in self._handlers.get(event, []):
            try:
                handler(payload)
            except Exception as e:
                from semente.logging import log_warning

                log_warning(
                    f"event handler {getattr(handler, '__name__', handler)!r} "
                    f"failed on {event.value}: {e}"
                )

    def subscriber_count(self, event: AgentEvents) -> int:
        return len(self._handlers.get(event, []))