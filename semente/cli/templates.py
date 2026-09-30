"""Scaffold templates for ``semente init`` — a working minimal app.

Modeled on the Pasto Legal reference app: a manifest, an .env.example with the
standard variable groups, a ``domain/`` package exposing ``domain_spec``, the
localized prompt files, and a FastAPI entry point for WhatsApp.
"""

from __future__ import annotations

from pathlib import Path

SEMENTE_YAML_TEMPLATE = """\
name: {name}
language: {language}
domain_module: domain
engine: agno
prompts_dir: domain/prompts
channels: [streamlit]
features:
  tts: true
  feedback_workflow: true
  summarization: true
  pii_guardrail: true
models:
  primary:
    provider: {provider}
    id: {model_id}
"""

_ENV_MODEL_BLOCK = {
    "google": """\
# ---- Model provider: google (Gemini) ----
PRIMARY_MODEL_PROVIDER="google"
PRIMARY_MODEL_ID="{model_id}"
GOOGLE_API_KEY=""
""",
    "ollama": """\
# ---- Model provider: ollama (local) ----
PRIMARY_MODEL_PROVIDER="ollama"
PRIMARY_MODEL_ID="{model_id}"
OLLAMA_HOST="http://localhost:11434"
OLLAMA_API_KEY=""
""",
}

ENV_EXAMPLE_TEMPLATE = """\
# Semente app — environment configuration.
# Copy to .env (same folder) and fill in your values, or run
#   semente launch streamlit
# and the first-run wizard fills the missing model values for you.

APP_ENV="development"

# ---- Storage: sqlite keeps everything local; postgres for production ----
DATABASE_TYPE="sqlite"

POSTGRES_HOST=""
POSTGRES_PORT=5432
POSTGRES_DBNAME=""
POSTGRES_USER=""
POSTGRES_PASSWORD=""

PGVECTOR_HOST=""
PGVECTOR_PORT=5432
PGVECTOR_DBNAME=""
PGVECTOR_USER=""
PGVECTOR_PASSWORD=""

{model_block}
# ---- Optional fallback model ----
# FALLBACK_MODEL_PROVIDER="ollama"
# FALLBACK_MODEL_ID="gemma4:31b-cloud"

# ---- WhatsApp channel (only when 'whatsapp' is in semente.yaml channels) ----
WHATSAPP_ACCESS_TOKEN=""
WHATSAPP_VERIFY_TOKEN=""
WHATSAPP_WEBHOOK_URL=""
WHATSAPP_PHONE_NUMBER_ID=""
WHATSAPP_APP_SECRET=""

# ---- S3 storage (required in production/stagging; ignored in development) ----
S3_ENDPOINT_URL=""
S3_ACCESS_KEY=""
S3_SECRET_KEY=""
S3_BUCKET="{name}"
S3_REGION=""
"""

DOMAIN_INIT_TEMPLATE = '''\
"""{name} domain — the DomainSpec Semente assembles into the app.

Replace the example tool with your own, add a knowledge base and skills as
needed (see the Semente docs: The Domain).
"""

from semente import tool
from semente.domain import DomainSpec


@tool(description="Echo the given message back to the user.")
def echo(message: str) -> str:
    """Return the message unchanged — an example tool to replace."""
    return f"Echo: {{message}}"


domain_spec = DomainSpec(
    name="{name}",
    tools=[echo],
)
'''

MAIN_PY_TEMPLATE = '''\
"""{name} entry point — assembles the app from the Semente framework.

Run with:  python main.py   (WhatsApp webhook on port 3000, when the
whatsapp channel is enabled in semente.yaml)
"""

from semente.build import build_app

app = build_app("semente.yaml")

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=3000, reload=True)
'''

GITIGNORE_TEMPLATE = """\
# Python
__pycache__/
*.py[cod]
.venv/

# Semente runtime artifacts
.env
logs/
tmp/
data/
users_db.json
.streamlit/secrets.toml
"""


def default_model_id(provider: str) -> str:
    from semente.configs.wizard import _DEFAULT_MODEL_ID, _OLLAMA_MODEL_ID

    return _OLLAMA_MODEL_ID if provider == "ollama" else _DEFAULT_MODEL_ID


def env_example_content(name: str, provider: str) -> str:
    model_block = _ENV_MODEL_BLOCK[provider].format(model_id=default_model_id(provider))
    return ENV_EXAMPLE_TEMPLATE.format(name=name, model_block=model_block)


def bundled_prompts_dir() -> Path:
    """The framework's bundled default prompts (copied into the scaffold)."""
    from semente.configs.prompts import DEFAULTS_DIR

    return DEFAULTS_DIR