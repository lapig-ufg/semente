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
  pii_guardrail: true{tutorial_feature_block}
models:
  primary:
    provider: {provider}
    id: {model_id}
"""

TUTORIAL_FEATURE_BLOCK = "\n  tutorial: true"

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

TUTORIAL_TEMPLATE = '''\
"""{name}'s guided tutorial — returned by the ``get_tutorial`` seam.

The framework owns the machinery: the welcoming agent offers the tutorial
and records the choice; a supervisor (the first tutorial agent) grades every
message against the step's ``forward_condition`` — the real assistant does
the work when it forwards; after its reply the step's
``complete_condition`` decides the move to the next step; the final outcome
is persisted. This object owns the content: how many steps and what each
one teaches. ``get_tutorial`` is passed to the DomainSpec in this package
and that is the whole contract — edit the steps freely, they are plain
English (or your users' language).

Each step:

    id                 Short stable key (labels the step in logs, prompts
                       and the offer menu).
    lesson             What this step teaches: one chat-style message with
                       the concrete action the user takes now.
    forward_condition  What counts as doing exactly what this step asks —
                       the supervisor forwards on it (any wording counts).
    complete_condition When the step is concluded, either:
                       - a str: judged by the checkpoint agent from the
                         conversation and the real assistant's reply;
                       - a callable: called with (session_state,
                         user_text, agent_reply) -> bool — read whatever
                         state your tools wrote to confirm it.
                       A False (or error) never advances the step.

The framework appends the congrats + the NEXT step's lesson (or the
closing) to the reply when a step completes. Customize the optional
``offer``/``closing``/``abandon`` texts on the Tutorial object when wanted
(None keeps the framework defaults).
"""

from semente.domain import Tutorial, TutorialStep


def get_tutorial() -> Tutorial:
    """The guided-tutorial spec — any number of steps, listed in order."""
    return Tutorial(
        steps=[
            TutorialStep(
                id="first-step",
                lesson=(
                    "Teach the user the concrete action of this first step "
                    "and ask them to do it in whichever way is easiest."
                ),
                forward_condition=(
                    "The user is doing or asking exactly this step's action "
                    "in any wording, or replying to the real assistant's "
                    "follow-up questions on the way."
                ),
                complete_condition=(
                    "The history plus the real assistant's latest reply show "
                    "this step's final result was delivered to the user."
                ),
            ),
            TutorialStep(
                id="second-step",
                lesson=(
                    "Teach the user the next thing {name} does and give one "
                    "short example of how to ask for it."
                ),
                forward_condition=(
                    "The user asks for any of this step's outcomes in "
                    "natural language, or answers the real assistant's "
                    "questions about it."
                ),
                complete_condition=(
                    "The history plus the real assistant's latest reply show "
                    "the asked outcome was delivered."
                ),
                # A callable condition instead of a str:
                # complete_condition=lambda session_state, user_text,
                #     agent_reply: bool(session_state.get("my_tool_result")),
                # Use any key your tools write to session_state.
            ),
            # Add or remove TutorialStep entries as needed — the count is
            # yours; the tutorial is as short or long as this list.
        ],
        # offer=None,     # custom text for the welcoming agent's ask
        # closing=None,   # custom final message after the last step
        # abandon=None,   # custom reply when the user leaves the tutorial early
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