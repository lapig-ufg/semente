# Semente development instance — Echo Domain toy app on Streamlit.
#
# Build from the repository root (the compose file next to this Dockerfile
# wires it up):
#   docker compose -f examples/echo_domain/compose.yml up --build
#
# The app runs with the example dir as its working directory, so
# SEMENTE_MANIFEST and the `domain` package resolve next to semente.yaml —
# the same layout as the documented local flow
# (`cd examples/echo_domain && semente streamlit`).

FROM python:3.12-slim

# uv, pinned to the version used to develop semente
COPY --from=ghcr.io/astral-sh/uv:0.11.6 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Dependencies first — this layer is cached across framework code changes
COPY pyproject.toml README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-install-project

# Framework + the example app
COPY semente ./semente
COPY examples ./examples
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync

# Runtime configuration.
# UV_NO_SYNC — the image is already synced; `uv run` must never re-sync.
# STREAMLIT_* — the semente CLI passes no flags to `streamlit run`, so the
# bind address and headless mode are set via streamlit's env vars.
ENV UV_NO_SYNC=1 \
    APP_ENV=development \
    SEMENTE_MANIFEST=semente.yaml \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_HEADLESS=true

# The app dir is the cwd: semente.yaml + domain/ live here
WORKDIR /app/examples/echo_domain

EXPOSE 8501

CMD ["uv", "run", "semente", "streamlit"]