"""Multimodal in on MyAgent — images, audio, and files, mocked, no network.

Covers: ``to_wire_parts`` resolving semente ``Image``/``Audio``/``File``
objects (content bytes / filepath read / url; mime by annotation or
extension; unresolvable dropped), the Gemini wire (typed ``inline_data`` /
``file_data`` parts, text + media in one Content), ``run()`` sending media
on the first round's user turn, and ``files`` also riding into tools
declaring a ``files`` parameter (framework convention).
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from google.genai.types import Blob, Content, FileData, Part

from semente.backends.base import AgentInput
from semente.backends.bare import MyAgent
from semente.backends.bare.media import to_wire_parts
from semente.backends.bare.providers import GeminiProvider, Provider
from semente.backends.bare.providers.base import GenerateResult, ToolCall
from semente.tools import tool
from semente.tools.types import Audio, File, Image, ToolResult


class _RecordingProvider(Provider):
    name = "fake"

    def __init__(self, results):
        self.results = iter(results)
        self.user_turns = []

    def generate(self, system, message=None, model_id=None, tools=None, history=None, media=None):
        return next(self.results)

    def user_turn(self, message, media=None):
        self.user_turns.append({"message": message, "media": media})
        return {"role": "user", "content": message, "media": media}

    def tool_results_turn(self, outputs):
        return [{"role": "tool", "outputs": outputs}]


def _tmp_file(data: bytes, suffix: str) -> Path:
    p = Path(tempfile.mkdtemp()) / f"item{suffix}"
    p.write_bytes(data)
    return p


# ---- to_wire_parts -------------------------------------------------------------


def test_to_wire_parts_content_bytes():
    parts = to_wire_parts(
        images=[Image(content=b"PNGDATA", mime_type="image/png")],
        audio=[Audio(content=b"AUDIODATA", mime_type="audio/wav")],
    )
    assert parts == [
        {"kind": "image", "mime_type": "image/png", "data": b"PNGDATA"},
        {"kind": "audio", "mime_type": "audio/wav", "data": b"AUDIODATA"},
    ]


def test_to_wire_parts_url_rides_as_url():
    parts = to_wire_parts(images=[Image(url="https://example.com/farm.png", mime_type="image/png")])
    assert parts == [{"kind": "image", "mime_type": "image/png", "url": "https://example.com/farm.png"}]


def test_to_wire_parts_filepath_read_with_mime_fallback():
    p = _tmp_file(b"JPEGBYTES", ".jpg")
    parts = to_wire_parts(images=[Image(filepath=p)])
    assert parts == [{"kind": "image", "mime_type": "image/jpeg", "data": b"JPEGBYTES"}]


def test_to_wire_parts_unresolvable_dropped():
    parts = to_wire_parts(
        images=[Image()],  # no content/url/filepath
        files=[File(filepath="/does/not/exist.png")],
    )
    assert parts == []


def test_to_wire_parts_file_kind():
    p = _tmp_file(b"{}", ".geojson")
    parts = to_wire_parts(files=[File(filepath=p)])
    assert parts == [{"kind": "file", "mime_type": "application/geo+json", "data": b"{}"}]


# ---- Gemini wire ---------------------------------------------------------------


def test_gemini_media_parts_inline_and_file_data():
    from semente.backends.bare.providers.gemini import _media_parts

    parts = _media_parts([
        {"kind": "image", "mime_type": "image/png", "data": b"PNG"},
        {"kind": "image", "mime_type": "image/png", "url": "https://x/y.png"},
    ])

    assert isinstance(parts[0], Part)
    assert isinstance(parts[0].inline_data, Blob)
    assert parts[0].inline_data.data == b"PNG"
    assert parts[0].inline_data.mime_type == "image/png"
    assert isinstance(parts[1].file_data, FileData)
    assert parts[1].file_data.file_uri == "https://x/y.png"


def test_gemini_user_turn_text_and_media():
    provider = GeminiProvider()
    turn = provider.user_turn("describe this", media=[
        {"kind": "image", "mime_type": "image/png", "data": b"PNG"},
    ])

    assert isinstance(turn, Content)
    assert turn.role == "user"
    assert turn.parts[0].text == "describe this"
    assert turn.parts[1].inline_data.data == b"PNG"


def test_gemini_generate_with_media():
    provider = GeminiProvider()
    fake = MagicMock()
    fake.models.generate_content.side_effect = lambda **kw: _text_genai("seen")
    provider._client = fake

    from google.genai.types import Candidate, Content as GContent, GenerateContentResponse, Part as GPart

    def _text_genai(text):
        return GenerateContentResponse(
            candidates=[Candidate(content=GContent(role="model", parts=[GPart(text=text)]))]
        )

    out = provider.generate(
        system="s",
        message="hi",
        media=[{"kind": "audio", "mime_type": "audio/wav", "data": b"WAV"}],
    )

    assert out.text == "seen"
    contents = fake.models.generate_content.call_args.kwargs["contents"]
    assert contents[0].parts[0].text == "hi"
    assert contents[0].parts[1].inline_data.data == b"WAV"


# ---- run(): media to the model, files also to tools ----------------------------


def test_run_sends_media_on_first_round_user_turn():
    provider = _RecordingProvider([GenerateResult(text="described")])
    agent = MyAgent(instructions="describe", provider=provider)

    turn = agent.run(AgentInput(
        text="what is in this?",
        images=[Image(content=b"PNGDATA", mime_type="image/png")],
        audio=[Audio(content=b"AUDIODATA", mime_type="audio/wav")],
        session_state={},
    ))

    assert turn.content == "described"
    first = provider.user_turns[0]
    assert first["message"] == "what is in this?"
    assert first["media"] == [
        {"kind": "image", "mime_type": "image/png", "data": b"PNGDATA"},
        {"kind": "audio", "mime_type": "audio/wav", "data": b"AUDIODATA"},
    ]


def test_run_files_go_to_model_and_into_tools():
    received = []

    @tool(description="import a shape")
    def import_shape(run_context, files: list) -> ToolResult:
        received.append(list(files))
        return ToolResult(content=f"imported {len(files)} file(s)")

    provider = _RecordingProvider([
        GenerateResult(tool_calls=[ToolCall(id="c1", name="import_shape", args={})], turn="model-turn"),
        GenerateResult(text="import done"),
    ])
    agent = MyAgent(instructions="s", provider=provider, tools=[import_shape])

    shape = File(content=b"{}", mime_type="application/geo+json", name="shape.geojson")
    turn = agent.run(AgentInput(text="import my shape", files=[shape], session_state={}))

    assert turn.content == "import done"
    # tool got the files (framework convention)
    assert received == [[shape]]
    # and the model saw them on the first round's user turn
    first = provider.user_turns[0]
    assert first["media"] == [
        {"kind": "file", "mime_type": "application/geo+json", "data": b"{}"}
    ]


def test_run_without_media_is_plain_text():
    provider = _RecordingProvider([GenerateResult(text="hello")])
    agent = MyAgent(instructions="s", provider=provider)

    agent.run(AgentInput(text="hi", session_state={}))

    first = provider.user_turns[0]
    assert first["message"] == "hi"
    assert first["media"] == []


if __name__ == "__main__":
    test_to_wire_parts_content_bytes()
    test_to_wire_parts_url_rides_as_url()
    test_to_wire_parts_filepath_read_with_mime_fallback()
    test_to_wire_parts_unresolvable_dropped()
    test_to_wire_parts_file_kind()
    test_gemini_media_parts_inline_and_file_data()
    test_gemini_user_turn_text_and_media()
    test_gemini_generate_with_media()
    test_run_sends_media_on_first_round_user_turn()
    test_run_files_go_to_model_and_into_tools()
    test_run_without_media_is_plain_text()
    print("Multimodal in tests OK")