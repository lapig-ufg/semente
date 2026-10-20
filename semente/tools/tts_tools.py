"""Agent-facing TTS tool shim.

This is a lightweight ``@tool`` that tags the agent response with an
``Audio`` carrying only the transcript — it does NOT synthesize audio here.
The actual speech synthesis happens once, at the end of the run, in
``Harness._finalize_output``, which calls the real implementation in
``semente.services.audio.tts.generate_speech``.

Keeping this as a shim lets the agent "claim" it produced audio so the
pipeline knows to synthesize speech for that turn, without paying the
synthesis cost on every intermediate agent run.
"""

from semente import Audio
from semente import tool
from semente import ToolResult
from semente.logging import log_debug, log_error

from semente.configs.prompts import get_tool_description


@tool(description=get_tool_description("tts_tools", "generate_speech"))
def generate_speech(text: str) -> ToolResult:
    """
    Generates spoken audio (text-to-speech conversion) from the provided text.

    WHEN TO USE:
    - Call this tool ONLY when the user explicitly requests an audio or voice response.
    - Call this tool if the current session or a system preference requires audio responses.

    Args:
        text (str): The full text of the content.

    Returns:
        ToolResult: Result object containing the generated speech.
    """
    log_debug("generate_speech: marking turn for audio synthesis")
    try:
        return ToolResult(content="Audio generated successfully!", audios=[Audio(content=bytes(), transcript=text)])
    except Exception as e:
        log_error(f"generate_speech: {e}")
        return ToolResult(content=f"Error generating audio: {str(e)}")