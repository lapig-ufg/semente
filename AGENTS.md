# AGENTS.md

Semente: a domain-neutral multi-agent chat framework (Python 3.12+, `uv`). Apps plug in via a **domain** (`DomainSpec` in `domain/__init__.py`) + **manifest** (`semente.yaml`). Full docs: `docs/` (see `docs/architecture/README.md` for the pipeline and package map).

## Commands

```bash
uv venv .venv && source .venv/bin/activate   # install: uv pip install -e ".[dev]"
.venv/bin/python -m pytest                   # all tests (hermetic, offline)
.venv/bin/python -m pytest tests/test_manifest.py -k name   # single test
```

- `tests/conftest.py` injects dummy `GOOGLE_API_KEY`/`OLLAMA_API_KEY` — tests build agents but never call an LLM. Don't rely on real API keys in tests.
- `scripts/check_backends.sh` — smoke test: every engine backend (agno/adk/bare) imports and builds.
- `scripts/check_domain_purity.sh` — verifies `domain/` and `examples/` have no `agno` imports.
- There is **no lint/typecheck/format config** — pytest plus the two scripts are the verification steps.

## Architecture rules (enforced, not just convention)

- **Domains must be engine-free.** Any `agno` import in `domain/` or `examples/` fails `check_domain_purity.sh`. All engine-specific code lives in `semente/backends/<engine>/`.
- **Tools cross engines through `semente/backends/toolkit.py`** (hooks, context, media bag, schema). Write tools once with the `@tool` decorator; `tests/test_parity.py` pins the agno path and the shared seam to identical schema/output/media.
- Engine selection: manifest `engine` field → `SEMENTE_ENGINE` env → `agno` default (`semente/backends/registry.py`).

## Gotchas

- **`.env` is loaded from `Path.cwd()` at import time** (`semente/configs/config.py`) — run an app from its own directory (e.g. `cd examples/minimal-chat && semente launch streamlit`, with `SEMENTE_MANIFEST=semente.yaml`).
- Manifest path resolution: constructor arg → `SEMENTE_MANIFEST` env → `./semente.yaml`.
- Dependency pins are deliberate: `starlette<0.46` and `streamlit<1.53` avoid a conflict (see comment in `pyproject.toml`); don't bump them without resolving the fastapi 0.115.8 pin.
- Geospatial/features are optional extras: `gee`, `geo`, `knowledge` (needs pgvector/Postgres), `weather`. Core install works without them.

## Entry points

- `semente.core.harness.Harness` owns a full user turn; every channel calls `get_harness().run(...)`. Agent construction: `semente/agents/build_agent.py`; programmatic app assembly: `semente/build.py` (`build_app(manifest)` → FastAPI ASGI).
- `semente` CLI (`semente/cli/`): `init`, `config`, `status`, `launch streamlit|whatsapp [--demo]`.

## Docs site

VitePress in `docs/` (`npm install && npm run dev`); deploys to GitHub Pages on push to `main` (the only CI workflow — tests are not run in CI).