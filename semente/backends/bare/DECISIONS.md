# bare/DECISIONS.md — MyAgent: decisions & progress

Status report for the from-scratch agent being built in this backend.
Updated: 2026-10-02 (multimodal in — images, audio, files).

## Goal

Own the LLM loop with zero framework dependency: no agno, no ADK, no
litellm. Semente already owns orchestration, state, sessions, media,
hooks, knowledge, and skills — the agent here only has to do chat, call
tools, and return text + media, over a vendor provider port.

## Architecture decisions

### D1 — Loop ownership: agent drives, provider round-trips
The **agent** owns the tool loop (parse calls → execute → feed results →
repeat). The **provider** does exactly one typed round-trip per call:
declarations in, text + tool calls out, plus building the provider-native
turns to echo back. Every round rides the accumulated history (round 1
included — `user_turn(message)` starts the list); the agent never passes a
one-shot `message` to `generate`. The cap (`_MAX_TOOL_ITERATIONS` provider
rounds) breaks before executing the cap round's calls — their results could
never be fed back, so running them would be wasted side effects (e.g. paid
map generation). Rationale: tool *execution* (hooks, run_context, media bag)
is engine-neutral and shared (`backends/toolkit.py`); a future `openai.py`
implements only the wire, never a second loop.

### D2 — Provider tools are semente `Tool` objects
`Provider.generate(..., tools)` receives the framework-native `Tool` class
(the `@tool` decorator's product), not vendor declarations. Conversion to
`FunctionDeclaration` happens inside `providers/gemini.py`, reusing the
shared `tool_schema` seam for the JSON schema.

### D3 — Tools callable receives `StateContext`, not the raw dict
`MyAgent(tools=...)` accepts a static list or
`Callable[[StateContext], list[Tool]]`, resolved against the run's state —
matching `AgentSpec.tools` and ADK, so `from_spec` and direct construction
share one path.

### D4 — Strong typing end to end (traceability)
No raw dicts on the vendor wire. Gemini messages are typed genai objects:
`FunctionDeclaration(parameters_json_schema=...)`, `Content`/`Part`,
`FunctionResponse`. The provider protocol uses provider-neutral
dataclasses (`ToolCall`, `GenerateResult`) so the agent never imports
vendor types.

### D5 — History is a list of opaque provider turns
The agent accumulates `provider.user_turn(message)`, the model's turn, and
`provider.tool_results_turn(outputs)`, passing the list back on each
round-trip. The agent never inspects entries; the provider interprets
them. The model's turn is echoed **verbatim** — Gemini 3 `thought_signature`
parts live there and must round-trip unmodified.

### D6 — Function responses use role "user" (Gemini), not "tool"
Verified against the SDK: `Content.role` docs say *"Must be either 'user'
or 'model'"*; `types.UserContent` hard-codes `user`; Google's own AFC loop
(`google.genai._extra_utils.get_function_response_parts`) builds bare
`Part.from_function_response` parts sent as user-role content.
`role: "tool"` is the **OpenAI** convention — wrong for Gemini. Do not
"fix" `tool_results_turn`.

### D7 — Routing: every spec goes to `MyAgent`
`BareBackend.build_agent` routes **every** spec to `MyAgent` — the former
litellm `BareAgentAdapter` fallback (`tool_loop.py`) was removed on
2026-10-02. Until MyAgent implements them natively, these capabilities are
gaps, not crashes: structured output (`output_schema`) yields `AgentTurn.
structured=None` (feedback/persona callers degrade gracefully) and
knowledge is ignored by the chat wire; multimodal input (D11) and
non-Google providers were closed or remain as noted in D11/D5.

### D8 — Event system: one mutable event object per emission
`MyAgent.subscribe(AgentEvents.X, handler)` hooks four events:
`AGENT_START` (session_state, by reference), `AGENT_END` (neutral message
log — `AgentMessage` user/assistant/tool, never provider-native turns, per
D5), `TOOL_EXECUTION_START` (tool_call_id, tool_name, args) before lookup,
`TOOL_EXECUTION_END` (tool_name, result, is_error) after. Handlers receive
the event dataclass itself: observers read fields; customizers assign them.
After the start event's handlers run, the agent executes whatever
`tool_name`/`args` the event carries — rename redirects to another tool,
unknown name feeds back "Unknown tool", a handler can rescue a bad model
call. **Execution vs wire**: mutations affect only what executes; the
provider echo always pairs the model's original call (id + name), so
`FunctionResponse` keeps matching the model's `FunctionCall`. Error
semantics: unknown tool → end event `is_error=True`, run continues; tool
exception → end event `is_error=True` then re-raise; provider failure → no
`AGENT_END`. Bus contract: handlers in subscription order (each sees prior
mutations); a handler exception is swallowed + logged (`log_warning`) — an
observer must never break a production run.

### D9 — Run metrics: provider-neutral usage dict at the seam
`GenerateResult.usage` carries one round's tokens as a provider-neutral
dict (`input_tokens`, `output_tokens`, `total_tokens`, `reasoning_tokens`,
`cache_read_tokens`, `tool_use_prompt_tokens`; absent counts dropped) —
vendor usage objects never leave the provider (D4). The run's accounting
lives in one **`AgentMetrics`** object (`metrics.py`), threaded through
the loop and tool calls instead of scattered locals: `start()` begins the
wall clock, `record_round(usage, round_duration)` per provider round,
`record_tool(name, duration, is_error)` per tool execution, `finish()`
at completion, `to_dict()` at the `AgentTurn` boundary — honoring the
`dict | None` contract (unlike agno, which stuffs its RunMetrics object
there). Token semantics: each round's wire usage is **cumulative for the
run** (the API counts the whole conversation so far), so the last round's
counts win — summed per round would double-count. Timing via
`perf_counter`. Per-tool `tools: [{name, duration, is_error}]` (unknown
tools and exceptions recorded `is_error=True`). No `cost` — the wire
carries no pricing. Debug-panel visibility of bare metrics is deferred
(its `extract_metrics` reads attributes, not dict keys).

### D10 — Skills: the engine-neutral skills module, natively on the agent
`MyAgent(skills=...)` accepts a ``Skills`` object or a callable
``(run_context) -> Skills | None`` resolved against the run's state — the
same pattern as ``instructions`` and ``tools``, nothing more. Building a
``Skills`` from directories is the caller's job (`load_skills` in the
pre-built engine-neutral `semente/skills.py`; no parallel bare copy).
`_resolve_skills` resolves per run (a callable returning anything but a
``Skills`` — or raising — logs a warning and degrades to no skills; the
run must not crash on a bad factory). `_execute` injects per run: the
`<skills_system>` snippet appended to the system instructions **and**
the three access tools
(`get_skill_instructions`/`get_skill_reference`/`get_skill_script`)
appended to the resolved tools — they ship together, since the snippet
tells the model to call the tools. `load_skills` list support: later
paths win on name collisions, missing paths are tolerated, `None` when
nothing loads. `from_spec` does **not** consume `spec.skills` natively —
the framework's `_with_skills` (build_agent.py) bakes snippet + tools
into the spec before any backend builds, so re-injecting would duplicate
the `<skills_system>` block (pinned by test).

### D11 — Multimodal in: neutral wire parts; files go to the model AND tools
`AgentInput.images`/`audio`/`files` become provider-neutral parts via
`media.py`'s `to_wire_parts` (semente `Image`/`Audio`/`File` resolved by
content bytes, filepath read, or url; mime by annotation or extension;
unresolvable entries dropped with a warning — one bad photo must not
sink the run). All three kinds ride the **first round's user turn**:
`user_turn(message, media)` mixes text and media parts, and
`generate(..., media)` gives one-shot calls the same parameter. The
provider converts to its native wire inside itself (Gemini: bytes →
`Part(inline_data=Blob)`, urls → `Part(file_data=FileData)` — D4, no raw
dicts). `files` additionally flow into tools declaring a `files`
parameter via `run_tool(input_files=...)` — the framework convention,
agno/ADK parity. `chat()` removed: `run(AgentInput)` is the single entry
point (the protocol primitive; chat was pre-protocol sugar only tests
used).

## File map

| File | Role |
|---|---|
| `agent.py` | `MyAgent`: instructions + tools + provider = the tool loop (cap 10 iterations) |
| `events.py` | `AgentEvents` + event dataclasses + `EventBus` (subscribe/emit, swallow+log) |
| `metrics.py` | `AgentMetrics` — per-run accumulator (`start`/`record_round`/`record_tool`/`finish`/`to_dict`) |
| `media.py` | `to_wire_parts` — semente `Image`/`Audio`/`File` → provider-neutral wire parts |
| `providers/base.py` | `Provider` ABC + `ToolCall`/`GenerateResult` dataclasses |
| `providers/gemini.py` | Gemini wire over `google-genai` (key/model from `config`, convention of `agno/models.py`) |
| `__init__.py` | `BareBackend` + routing (every spec → `MyAgent`) |

## Progress

| Date | Step | Commit |
|---|---|---|
| 2026-09 | `Provider` ABC + `GeminiProvider` (google-genai, no litellm) + chat-only `MyAgent(instructions, provider, model_id)` with `chat(str) -> str` | `3355382` |
| 2026-09 | Backend routing: pure-chat specs → MyAgent; litellm loop moved verbatim to `tool_loop.py`; `MyAgent` gains `from_spec`/`run` (Agent protocol) + callable instructions | `a428579` |
| 2026-09 | `GenerateContentConfig` replaces raw dict config (typed wire) | (uncommitted then) |
| 2026-10-01 | First tool loop: new provider protocol (`tools`, `history`, `user_turn`, `tool_results_turn`), typed Gemini function calling, agent-driven loop, routing extended to tool specs, tests built on real genai types | that commit |
| 2026-10-02 | litellm fallback (`tool_loop.py`, `BareAgentAdapter`) removed; every spec routes to `MyAgent`; `litellm` dropped from project dependencies | this commit |
| 2026-10-02 | Event system (D8): `events.py` (`AgentEvents`, payload dataclasses, `EventBus`); loop emits `AGENT_START`/`AGENT_END` + per-tool start/end; mutations on the start event redirect execution | this commit |
| 2026-10-02 | Canonical loop: `_execute` restructured into one flat generate→execute→feed-back cycle (every round rides history, incl. round 1; cap round's calls not executed; single `AGENT_END` site); iteration-cap test added | this commit |
| 2026-10-02 | Run metrics (D9): `GenerateResult.usage` extracted off the Gemini wire; `_execute` returns `(text, metrics)` — token counts, round/tool timings, `provider_rounds`; `AgentTurn.metrics` populated | this commit |
| 2026-10-02 | `AgentMetrics` class: the run's accounting moved from `_execute` locals into one object (`start`/`record_round`/`record_tool`/`finish`/`to_dict`), threaded through the loop and `_run_one`; `to_dict()` at the `AgentTurn` boundary; lives in `metrics.py` (metrics are not events) | this commit |
| 2026-10-02 | Skills (D10): `MyAgent(skills=...)` takes a `Skills` object or a callable `(run_context) -> Skills \| None` resolved per run (mirrors instructions/tools; `load_skills` list support is the caller-side loader); `_execute` injects the `<skills_system>` snippet + access tools per run; `from_spec` does not re-inject (framework path pre-bakes) | this commit |
| 2026-10-02 | Multimodal in (D11): `media.py` (`to_wire_parts`), provider seam gains `media` (Gemini: inline_data/file_data, typed), images/audio/files ride the first round's user turn, files also tool-injected; `chat()` removed — `run(AgentInput)` is the single entry point | this commit |

Tests: `tests/test_bare_myagent.py` (26, mocked genai — no network),
`tests/test_bare_events.py` (17, mocked provider — no network),
`tests/test_bare_skills.py` (11, mocked provider — no network),
`tests/test_bare_media.py` (11, mocked provider + typed genai — no
network); `tests/test_bare_backend.py` covered the removed litellm path
and was deleted with it.

## Next steps (candidates, unordered)

- Structured output on `MyAgent` (typed response schema)
- Multimodal input on the Gemini provider (images/audio parts)
- A second provider (openai.py or ollama.py) to prove the port's shape
- Real-key smoke test of the full loop (docs: AGNOSTIC_PENDING.md)
- History/session ownership question for `chat()` (currently stateless
  by design — sessions belong to the orchestrator)