"""Interactive environment wizard — first-run setup for the model block.

Runs before the Streamlit interface starts (``semente launch streamlit``). Values are
checked against the *effective* environment: the shell environment merged with
the app's ``.env`` file (the same merge ``load_dotenv`` performs at config
import). When every required variable resolves, the wizard stays silent; when
something is missing, it asks only for the gaps and persists the answers to
``.env`` so subsequent runs skip it entirely.

Non-interactive contexts (Docker, CI — stdin not a TTY) never prompt: they
print a warning listing what is missing and let the launch proceed.
"""

from __future__ import annotations

import os
import sys
from getpass import getpass
from pathlib import Path

DEFAULT_ENV_PATH = Path.cwd() / ".env"

_DEFAULT_MODEL_ID = "gemini-3.5-flash-lite"
_OLLAMA_MODEL_ID = "gemma4:31b-cloud"

# Required keys per provider. ``PRIMARY_MODEL_PROVIDER``/``PRIMARY_MODEL_ID``
# always count as required; the provider adds its key block.
_PROVIDER_KEYS: dict[str, list[str]] = {
    "google": ["GOOGLE_API_KEY"],
    "ollama": ["OLLAMA_HOST", "OLLAMA_API_KEY"],
}


def _parse_env_file(path: Path) -> dict[str, str]:
    """Read KEY=VALUE pairs from a .env file (comments/blank lines ignored)."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip()
    return values


def effective_env(env_path: Path = DEFAULT_ENV_PATH) -> dict[str, str]:
    """Shell environment overlaid with the .env file (env vars win, like load_dotenv)."""
    merged = dict(os.environ)
    for key, value in _parse_env_file(env_path).items():
        merged.setdefault(key, value)
    return merged


def required_keys(env: dict[str, str]) -> list[str]:
    """The model block required to run: provider, model id, provider keys."""
    provider = (env.get("PRIMARY_MODEL_PROVIDER") or "google").strip().lower()
    keys = ["PRIMARY_MODEL_PROVIDER", "PRIMARY_MODEL_ID"]
    keys += _PROVIDER_KEYS.get(provider, [])
    return keys


def get_missing(env: dict[str, str]) -> list[str]:
    """Required keys absent or empty in the effective environment."""
    return [key for key in required_keys(env) if not (env.get(key) or "").strip()]


def run_wizard(
    missing: list[str],
    env: dict[str, str],
    input_fn=input,
    getpass_fn=getpass,
) -> list[dict[str, str]]:
    """Interactively fill the missing keys. Returns ``[{"key": ..., "value": ...}]``.

    Provider keys are resolved against the *chosen* provider, so switching
    providers mid-wizard asks for the right key block even though ``missing``
    was computed beforehand.
    """
    answers: list[dict[str, str]] = []
    provider = (env.get("PRIMARY_MODEL_PROVIDER") or "google").strip().lower()

    if "PRIMARY_MODEL_PROVIDER" in missing:
        answer = input_fn(f"Model provider (google/ollama) [{provider}]: ").strip().lower()
        provider = answer or provider
        answers.append({"key": "PRIMARY_MODEL_PROVIDER", "value": provider})

    if "PRIMARY_MODEL_ID" in missing:
        default_id = _OLLAMA_MODEL_ID if provider == "ollama" else _DEFAULT_MODEL_ID
        default = (env.get("PRIMARY_MODEL_ID") or "").strip() or default_id
        answer = input_fn(f"Model ID [{default}]: ").strip()
        answers.append({"key": "PRIMARY_MODEL_ID", "value": answer or default})

    for key in _PROVIDER_KEYS.get(provider, []):
        if key not in missing and (env.get(key) or "").strip():
            continue
        default = (env.get(key) or "").strip()
        if key.endswith("_API_KEY"):
            hint = f" (default set)" if default else ""
            answer = getpass_fn(f"{key}{hint}: ").strip()
        else:
            hint = f" [{default}]" if default else ""
            answer = input_fn(f"{key}{hint}: ").strip()
        answers.append({"key": key, "value": answer or default})

    return answers


def save_to_env_file(env_path: Path, answers: list[dict[str, str]]) -> None:
    """Merge answers into .env: existing keys replaced in place, new keys appended."""
    by_key = {a["key"]: a["value"] for a in answers}
    lines = (
        env_path.read_text(encoding="utf-8").splitlines()
        if env_path.exists()
        else []
    )

    replaced: set[str] = set()
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.partition("=")[0].strip()
            if key in by_key:
                out.append(f"{key}={by_key[key]}")
                replaced.add(key)
                continue
        out.append(line)

    new_keys = [k for k in by_key if k not in replaced]
    if new_keys and out and out[-1].strip():
        out.append("")
    for key in new_keys:
        out.append(f"{key}={by_key[key]}")

    env_path.write_text("\n".join(out) + "\n", encoding="utf-8")


def ensure_config(
    env_path: Path = DEFAULT_ENV_PATH,
    stdin=sys.stdin,
    input_fn=input,
    getpass_fn=getpass,
) -> list[dict[str, str]]:
    """Pre-flight: ask for missing required vars and persist them to .env.

    Returns the answers (empty when nothing was missing). Exports each answer
    to ``os.environ`` so the spawned Streamlit process inherits it immediately.
    Non-TTY stdin never prompts — it warns and returns empty.
    """
    env = effective_env(env_path)
    missing = get_missing(env)
    if not missing:
        return []

    if stdin is not None and not stdin.isatty():
        print(f"WARNING: missing environment variables: {', '.join(missing)}")
        print(f"(interactive setup skipped — fill them in {env_path} or export them)")
        return []

    print("Semente needs a few values to run the model (saved to .env, asked only once):")
    answers = run_wizard(missing, env, input_fn=input_fn, getpass_fn=getpass_fn)
    if answers:
        save_to_env_file(env_path, answers)
        for answer in answers:
            os.environ[answer["key"]] = answer["value"]
        print(f"Saved to {env_path}.")
    return answers