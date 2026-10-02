"""Gemini provider — google-genai client, no framework, no litellm.

Model/key resolution follows the engine-neutral convention (see
``backends/agno/models.py``): ``config`` resolves key + model id, this module
turns them into a ``genai.Client`` and speaks the vendor's API.
"""

from __future__ import annotations

from semente.backends.bare.providers.base import Provider
from semente.configs.config import config


class GeminiProvider(Provider):
    name = "gemini"

    def __init__(self, api_key: str | None = None, model_id: str | None = None):
        from google import genai

        api_key = api_key or config.GOOGLE_API_KEY
        if api_key is None:
            raise ValueError("GOOGLE_API_KEY environment variable must be set.")
        self.api_key = api_key
        self.default_model = model_id or config.PRIMARY_MODEL_ID
        self._client = genai.Client(api_key=api_key)

    def generate(self, system: str, message: str, model_id: str | None = None) -> str:
        model = model_id or self.default_model
        resp = self._client.models.generate_content(
            model=model,
            contents=message,
            config={"system_instruction": system} if system else None,
        )
        return resp.text or ""