"""Run metrics — the per-run accounting object for ``MyAgent``.

``AgentMetrics`` is created at run start and threaded through the loop and
tool calls instead of scattered locals: every provider round and tool
execution is recorded as it happens, and ``to_dict()`` converts the object
into the dict stuffed into ``AgentTurn.metrics`` (decision D9).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter

_TOKEN_KEYS = (
    "input_tokens",
    "output_tokens",
    "total_tokens",
    "reasoning_tokens",
    "cache_read_tokens",
    "tool_use_prompt_tokens",
)


@dataclass
class AgentMetrics:
    """Per-run metrics accumulator — one object threaded through the run.

    The agent creates it at run start, updates it as the loop runs
    (``record_round`` per provider round, ``record_tool`` per tool
    execution, ``finish`` once at the end), and converts it via ``to_dict``
    into the dict stuffed into ``AgentTurn.metrics``.

    Token semantics: each provider round's wire usage is **cumulative for
    the run** (the API counts the whole conversation so far), so the last
    round's counts win — merging would double-count.
    """

    provider: str = ""
    model_id: str | None = None
    provider_rounds: int = 0
    duration: float = 0.0
    time_to_first_token: float | None = None
    round_durations: list[float] = field(default_factory=list)
    tools: list[dict] = field(default_factory=list)
    tokens: dict[str, int] = field(default_factory=dict)

    def __post_init__(self):
        self._started = perf_counter()

    @classmethod
    def start(cls, provider: str, model_id: str | None = None) -> AgentMetrics:
        """Begin a run's accounting (starts the wall clock)."""
        return cls(provider=provider, model_id=model_id)

    def record_round(self, usage: dict | None = None, round_duration: float | None = None) -> None:
        """One provider round completed: count it, time it, merge wire usage."""
        if round_duration is None:
            round_duration = perf_counter() - self._started
        self.round_durations.append(round_duration)
        self.provider_rounds += 1
        if self.time_to_first_token is None:
            self.time_to_first_token = round_duration
        if usage:
            self.tokens.update(usage)  # cumulative wire usage — last round wins

    def record_tool(self, name: str, duration: float, is_error: bool) -> None:
        """One tool execution completed (or failed to resolve)."""
        self.tools.append({"name": name, "duration": duration, "is_error": is_error})

    def finish(self) -> None:
        """Stop the wall clock — call once when the run completes."""
        self.duration = perf_counter() - self._started

    def to_dict(self) -> dict:
        """The dict for ``AgentTurn.metrics`` (contract in ``backends/base.py``)."""
        return {
            "provider": self.provider,
            "model_id": self.model_id,
            "provider_rounds": self.provider_rounds,
            "duration": self.duration,
            "time_to_first_token": self.time_to_first_token,
            "round_durations": self.round_durations,
            "tools": self.tools,
            **{k: self.tokens.get(k, 0) for k in _TOKEN_KEYS},
        }