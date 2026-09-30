# ADK_PARITY.md — full tool support on the ADK backend

**Goal:** run Pasto Legal on `SEMENTE_ENGINE=adk` with feature parity to Agno:
every domain tool works — media-returning tools (maps, PDF boletim, video),
knowledge-base Q&A, skills, tool hooks (registration gating, media
debouncing), and model fallback.

**Current state (verified):** dynamic tools resolve per registration state
(27 default / 3 pending), tool state syncs back to the Semente store,
toolkits expand, multimodal input works, structured output parses. **Done:**
media OUT (A-M), knowledge (A-K), tool hooks (A-H). **Missing:** skills,
fallback — see §2.

---

## 1. Why ADK doesn't support all tools today — the root differences

The two engines disagree on **who owns the tool pipeline**. Agno treats tools
as rich framework objects that carry media through the agent loop; ADK treats
tools as plain functions whose result is fed back to the LLM as text.

| # | Seam | Agno | ADK | Consequence |
|---|---|---|---|---|
| 1 | **Tool result media** | `ToolResult` (pydantic: content + images/videos/audios/files) propagates through the loop into `RunOutput.images` → channels send them | Tools are plain functions returning `str`/`dict`; the response is content parts only — **no media artifact propagation exists** | Pasto Legal's 6 media tools (biomass/classification/soil/property images, biomass video, boletim PDF) produce text-only results on ADK |
| 2 | **Framework-injected capabilities** | `Agent(knowledge=…, search_knowledge=True)` **auto-injects** a `search_knowledge_base` tool + retrieval instructions; skills injected on demand | No auto-injection; ADK "knowledge" = Vertex AI Search toolsets (a different, cloud-Google stack) | EMBRAPA KB Q&A absent on ADK; the ua-calculator skill is ignored |
| 3 | **Tool hooks** | Per-tool wrapper hooks: `(run_context, function_call, arguments)`, return a value → short-circuit; `validate_rate_limit_hook` **calls the tool itself** and manages a 7-day media cache in session state | Agent-level `before_tool_callback`/`after_tool_callback`: `(tool, args, tool_context) -> dict` (dict = skip). A hook that *executes* the tool cannot be expressed as before/after callbacks | Registration gating ("no property selected") and media dedup are not enforced on ADK |
| 4 | **Tool definition** | Decorated `Function` objects; tools/instructions may be **callables re-evaluated per run** | Plain typed+docstring functions, **static at build time**; node names must be identifiers; `output_schema`+tools together only on some models | Solved for Pasto Legal by rebuilding the `LlmAgent` per run (ff57fed) — kept as a permanent design choice |
| 5 | **Session state** | `RunContext.session_state` — an in-place mutated dict, shared by reference; anything goes | `ToolContext.state` — event-tracked `state_delta` with prefix scopes (`user:`, `temp:`), values must be JSON-serializable, direct mutation discouraged/broken | Solved by seed + sync-back (ff57fed); Pasto Legal's state is JSON-safe (verified) |
| 6 | **Model layer** | Model objects (`Gemini(api_key, temperature)`); **`fallback_models` retries inside the engine** | Model as a *string id* + `generate_content_config`; no fallback concept | Fallback dropped in the Phase H port — **for every engine** (regression found by this audit; fixed in Phase F below) |

The meta-difference: **Agno is a rich tool framework; ADK is a thin function-calling contract.** Everything Agno does *for* you between the tool and the channel, Semente must now do itself — which is exactly what the engine port was designed for (MULTI_ENGINE.md Discovery 2: *media doesn't need to flow through the LLM loop*).

---

## 2. Gap inventory → fix designs

### G1 — Media OUT (maps, video, PDF boletim) ★ the core piece

**Fix: per-run MediaBag inside the ADK adapter.** The adapter already
rebuilds the agent per run, so `_adapt_tool` wrappers can capture a per-run
`media_bag` list by closure: tool returns a Semente `ToolResult` → the
wrapper stashes `images/videos/audios/files` in the bag and passes **only the
text content** to ADK (which is all ADK can consume anyway). After
`runner.run(...)`, the adapter attaches the bag to `AgentTurn(images=…,
videos=…, audios=…, files=…)` — and `SementeAgent._invoke_agent` **already
maps `AgentTurn.media` onto `StepOutput`**, which the WhatsApp router and
Streamlit already display. Zero changes to channels, the agent pipeline, or
the working Agno path.

```python
# sketch — inside AdkAgentAdapter.run
bag: list = []                       # per-run, captured by closure
tools = [_adapt_tool(t, bag) for t in resolved]
... run ...
turn.images  = [m for k, m in bag if k == "images"]  # etc.
```

### G2 — Knowledge base (EMBRAPA Q&A)

**Fix: Semente-owned retrieval tool.** Build `search_knowledge_base(query)`
from the KB's vector DB (the `semente.knowledge.build_knowledge()` factory
already owns the machinery). When `spec.knowledge` is set, the ADK backend
injects this tool **plus** the same retrieval-instruction block Agno
auto-generates (`add_search_knowledge_instructions`), so prompt behavior
matches. Spike: confirm the agno `Knowledge` retrieval entry point
(`vector_db.search` vs a `Knowledge.search` helper) — half day. Agno keeps
its native path untouched; unification to one path is a later cleanup.

### G3 — Skills (ua-calculator)

**Fix: instruction injection.** Extend `semente.skills` with a native
SKILL.md reader (frontmatter + body). The ADK backend appends skill content
to the instruction provider output (capabilities block). Agno keeps its
on-demand `LocalSkills` behavior.

### G4 — Tool hooks (registration gating + media dedup)

**Fix: replicate Agno's hook protocol in the Semente tool wrapper — do NOT
map to ADK callbacks.** The hooks are extracted at adapt time from the agno
`Function` objects (`tool.tool_hooks`) and applied *around the raw function*
in the wrapper, in order, with Agno semantics: hook returns a non-`None`
value → that becomes the tool result and the tool is not called;
`validate_rate_limit_hook` executes the function itself and manages the
`delivered_media` cache — all of this works because the wrapper *is* the
executor. The bridge provides a `function_call` stand-in exposing
`__name__` + `(**arguments)` to satisfy both hooks. ADK only ever sees the
final string.

### G5 — Model fallback (regression, all engines)

**Fix: Semente-level fallback wrapper (engine-agnostic).** Add
`fallback_model: ModelSpec | None` to `AgentSpec` (populated from the
manifest's `models.fallback` — currently parsed but discarded). In
`SementeAgent._invoke_agent` (the single place every engine's `run` flows
through): try the agent; on exception or empty content, build a fallback
agent once (lazily) and retry. This restores the behavior Pasto Legal had on
Agno and gives every backend the same guarantee.

### G6 — Tool-call log for the debug panel (optional)

ADK events carry function calls/responses; accumulate them into
`AgentTurn.tools` so the Streamlit debug panel shows tool traces on ADK like
it does on Agno. Cosmetic — deferable.

---

## 3. Phases

### Phase A-M — MediaBag on ADK (1 day) ★ unblocks all 6 media tools
- [x] Per-run media bag in `AdkAgentAdapter` (closure capture, attach to `AgentTurn`)
- [x] Unit test: a media tool's ToolResult → bag → `StepOutput.images` via `SementeAgent._invoke_agent`
- [ ] Integration (real key): `generate_property_image` on Streamlit/ADK shows the map
- **Exit:** biomass image + boletim PDF render on ADK.

### Phase A-K — Knowledge tool (1.5 days)
- [x] Spike: agno KB retrieval entry point
- [x] `semente.knowledge.build_search_tool(kb)` + instruction block mirroring Agno's
- [x] ADK backend injects when `spec.knowledge` is set
- **Exit:** a platform question ("como funciona o cadastro?") on ADK answers from the EMBRAPA KB, not general knowledge.

### Phase A-H — Tool hooks bridge (1.5 days)
- [x] Extract `tool_hooks` from agno `Function` at adapt time
- [x] Hook protocol replication in the wrapper (+ `function_call` stand-in)
- [x] Tests: analysis tool blocked without a registered property (both engines behave identically); media dedup marks `delivered_media`
- **Exit:** asking for biomass **before** registering a property returns the polite gating message on ADK, same as Agno.

### Phase A-S — Skills injection (0.5 day)
- [ ] Native SKILL.md reader in `semente.skills`; ADK appends to instructions
- **Exit:** ua-calculator guidance present in ADK instructions.

### Phase A-F — Fallback models (1 day, fixes the regression for ALL engines)
- [ ] `AgentSpec.fallback_model`; populated from manifest `models.fallback`
- [ ] Retry wrapper in `SementeAgent._invoke_agent` (build fallback agent lazily, retry once)
- [ ] Test with a bogus primary model id + working fallback on both engines
- **Exit:** `PRIMARY_MODEL_ID=invalid` + valid fallback → app still answers on agno AND adk.

### Phase A-P — Parity harness (1.5 days)
- [ ] Adapter-level golden tests (no network): tool resolution per state, hook gating, media bag, state sync — asserting **identical StepOutput shapes** across agno/adk adapters with mocked model responses
- [ ] Manual smoke checklist documented (the flow from the ADK test instructions: terms → register → diagnosis → weather)

**Total ≈ 1.5–2 weeks part-time.** Each phase lands independently and is
committable on its own; A-M first (highest value), then A-K/A-H, then A-S,
A-F, A-P.

---

## 4. Risks

| Risk | Mitigation |
|---|---|
| Agno `Knowledge` retrieval API differs from assumed | Half-day spike gates A-K; worst case query `vector_db.search` directly (the factory owns the DB object) |
| Hook bridge drifts from Agno semantics (return-value vs sentinel) | Port the exact agno hook-invocation code as reference; golden tests on both engines |
| Per-run agent rebuild + per-run `InMemorySessionService` is slower than Agno | Measured cost is tool-schema generation (27 tools) — acceptable for a chat turn; cache the static tool schemas across runs later if it shows |
| ADK state prefix collisions (`user:`/`app:` keys in Pasto Legal state) | Verified none today; sync-back filters `temp:` and asserts serializability in tests |
| Fallback retry masks real errors | Log the primary failure at error level; retry only on exception/empty content, not on guardrail `stop` |

## 5. Honest residual degradations (even at "full parity")

- **Debug panel richness**: reasoning content and native tool traces are richer on Agno (A-G6 narrows this)
- **Streaming** (Phase 2 of the agent pipeline roadmap) still applies to both engines equally — not ADK-specific
- **TTS**: engine-independent (direct `google-genai`), unaffected
- **ADK `output_schema`+tools model restriction**: our structured-output agents are tool-free (asserted in CI), so it never bites — but the constraint means Semente can never give a *tool-using* agent a schema on ADK where Agno could

## 6. What this buys beyond ADK

G5 (fallback) fixes a regression on **every** engine. G1's per-run bag
design is the thin end of the full MediaBag architecture (MULTI_ENGINE.md
Discovery 2): once proven on ADK, unifying the Agno path onto it is a small
step that removes the last media asymmetry between engines.