"""Shared test fixtures.

The agno backend builds model objects at agent-construction time and requires
an API key even when no LLM call is ever made (hermetic tests). Provide a
dummy key when none is configured — real runs use the app's .env.
"""

import os


def _ensure_dummy_api_keys():
    if not os.environ.get("GOOGLE_API_KEY"):
        os.environ["GOOGLE_API_KEY"] = "dummy-test-key"
    if not os.environ.get("OLLAMA_API_KEY"):
        os.environ["OLLAMA_API_KEY"] = "dummy-test-key"


_ensure_dummy_api_keys()