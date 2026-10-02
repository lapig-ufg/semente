"""MyAgent + GeminiProvider tests — mocked genai client, no network.

Covers the chat-only loop: provider dispatch, system-instruction passing,
default model resolution, and the missing-key guard.
"""

from unittest.mock import MagicMock, patch

from semente.backends.bare.agent import MyAgent
from semente.backends.bare.providers import GeminiProvider, Provider
from semente.configs.config import config


class _FakeProvider(Provider):
    name = "fake"

    def __init__(self, reply="pong"):
        self.reply = reply
        self.calls = []

    def generate(self, system, message, model_id):
        self.calls.append((system, message, model_id))
        return self.reply


def _fake_client(reply="gemini says hi"):
    fake = MagicMock()
    fake.models.generate_content.return_value.text = reply
    return fake


def test_myagent_chat_returns_reply():
    provider = _FakeProvider(reply="hello back")
    agent = MyAgent(instructions="be nice", provider=provider)
    assert agent.chat("hi") == "hello back"
    assert provider.calls == [("be nice", "hi", None)]


def test_myagent_defaults_to_gemini_provider():
    agent = MyAgent(instructions="be nice")  # dummy key from conftest
    assert isinstance(agent.provider, GeminiProvider)
    assert agent.model_id == config.PRIMARY_MODEL_ID


def test_gemini_generate_sends_system_instruction():
    provider = GeminiProvider()
    fake = _fake_client()
    provider._client = fake

    out = provider.generate(system="be nice", message="hi", model_id="gemini-3.5-flash-lite")

    assert out == "gemini says hi"
    fake.models.generate_content.assert_called_once_with(
        model="gemini-3.5-flash-lite",
        contents="hi",
        config={"system_instruction": "be nice"},
    )


def test_gemini_generate_uses_default_model():
    provider = GeminiProvider()
    fake = _fake_client("ok")
    provider._client = fake

    provider.generate(system="s", message="m", model_id=None)

    assert fake.models.generate_content.call_args.kwargs["model"] == provider.default_model


def test_gemini_generate_without_system_passes_none_config():
    provider = GeminiProvider()
    fake = _fake_client("ok")
    provider._client = fake

    provider.generate(system="", message="hi", model_id="m")

    fake.models.generate_content.assert_called_once_with(model="m", contents="hi", config=None)


def test_gemini_missing_key_raises():
    with patch.object(config, "GOOGLE_API_KEY", None):
        try:
            GeminiProvider()
        except ValueError as e:
            assert "GOOGLE_API_KEY" in str(e)
        else:
            raise AssertionError("expected ValueError for missing GOOGLE_API_KEY")


if __name__ == "__main__":
    test_myagent_chat_returns_reply()
    test_myagent_defaults_to_gemini_provider()
    test_gemini_generate_sends_system_instruction()
    test_gemini_generate_uses_default_model()
    test_gemini_generate_without_system_passes_none_config()
    test_gemini_missing_key_raises()
    print("MyAgent tests OK")