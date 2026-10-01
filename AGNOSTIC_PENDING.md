# AGNOSTIC_PENDING.md — remaining work for engine-agnosticity

Updated 2026-09-09. The engine-agnostic core is now complete: native tool
layer, native skills, native Calculator, config decoupling, TTS/media/logging
internalized, model fallback, and the A-P parity harness. The only agno
coupling left outside the agno backend is the knowledge *storage* stack
(decided: agno-as-KB-library, see below).

## Done (this pass)

| # | Item | Result |
|---|---|---|
| A-F | Model fallback | `FallbackAgent` wrapper; manifest `models.fallback` + env resolved; all engines |
| #2 | Config decoupling | agno model classes moved to `backends/agno/models.py`; config resolves provider+id only |
| #1 | Native tool layer | `semente.tool()` returns a native `Tool`; agno converts at the boundary |
| #7 | Calculator | Native stdlib toolkit (8 ops), same `exclude_tools` API |
| #4 (A-S) | Skills | Native SKILL.md reader + `Skills` container; injected engine-agnostically (ADK/bare now get skills) |
| #5 | TTS | Returns Semente `Audio` |
| — | Type-hint imports | `RunContext` → `semente.context.Context` (persona/feedback/tool_hooks) |
| — | Dead code | Deleted `hooks/pre_hooks.py`, `services/transcription.py` |
| — | Logging | `semente/logging.py` stdlib facade; whatsapp helpers inlined `pcm_to_wav_bytes`/`get_image_type` |
| A-P | Parity harness | `tests/test_parity.py`: schema + result + media parity across agno/shared-seam |

## Decided

- **#3 Knowledge**: **agno-as-KB-library** (0 days). The embedder/chunking/
  PgVector/ChromaDb storage classes stay agno; retrieval is already
  engine-neutral (`build_search_tool`). Full de-agno (~3-4 days) deferred
  until a non-agno deployment needs it. Documented in `knowledge/__init__.py`.

## Remaining (deferred, not blocking)

- **Streaming (Phase 2)**: `Agent.stream()` protocol + streaming in the
  Semente pipeline; all engines have streaming primitives.
- **G6** (cosmetic): tool-call log on ADK/bare for the debug panel.
- **Real-key smokes**: ADK media delivery + bare full flow with real keys
  (only dummy-key graceful-400 verified so far).

## Recommended order (if resumed)

Streaming → G6 → (real-key smokes: done for ADK + bare in Feb 2026).