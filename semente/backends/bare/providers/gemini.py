"""Gemini provider — google-genai client, no framework.

Model/key resolution follows the engine-neutral convention (see
``backends/agno/models.py``): ``config`` resolves key + model id, this module
turns them into a ``genai.Client`` and speaks the vendor's API.

Strongly typed end to end: semente ``Tool``s become
``FunctionDeclaration``s (reusing the shared ``tool_schema`` seam for the
JSON schema), responses are parsed off typed ``Content``/``Part`` objects,
and the model's turn is echoed back verbatim — preserving Gemini 3
``thought_signature`` parts — before typed ``FunctionResponse`` parts.
"""

from __future__ import annotations

from semente.backends.bare.providers.base import GenerateResult, Provider, ToolCall
from semente.backends.toolkit import tool_schema
from semente.configs.config import config
from semente.tools.types import Tool


def _function_declaration(tool: Tool):
    """Semente Tool -> typed genai FunctionDeclaration.

    ``parameters_json_schema`` takes a raw JSON schema, so the shared
    engine-neutral ``tool_schema`` seam feeds straight in.
    """
    from google.genai.types import FunctionDeclaration

    schema = tool_schema(tool)
    return FunctionDeclaration(
        name=schema["name"],
        description=schema["description"] or None,
        parameters_json_schema=schema["parameters"],
    )


def _parse_response(resp) -> GenerateResult:
    """Typed response -> GenerateResult (text, calls, verbatim turn)."""
    from google.genai.types import Content, FunctionCall, Part

    content: Content | None = None
    parts = []
    for candidate in getattr(resp, "candidates", None) or []:
        if getattr(candidate, "content", None) is not None:
            content = candidate.content
            parts.extend(content.parts or [])
            break

    text = "".join(p.text for p in parts if getattr(p, "text", None))
    calls = [
        ToolCall(id=fc.id, name=fc.name, args=dict(fc.args or {}))
        for p in parts
        if (fc := getattr(p, "function_call", None)) is not None
        and isinstance(fc, FunctionCall)
    ]
    turn = content if (calls or text) else None
    return GenerateResult(text=text, tool_calls=calls, turn=turn)


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

    def generate(
        self,
        system: str,
        message: str | None = None,
        model_id: str | None = None,
        tools: list[Tool] | None = None,
        history: list | None = None,
    ) -> GenerateResult:
        from google.genai.types import Content, GenerateContentConfig, Part, Tool as GenaiTool

        model = model_id or self.default_model
        config = GenerateContentConfig(system_instruction=system) if system else None
        if tools:
            declarations = [_function_declaration(t) for t in tools]
            config = config or GenerateContentConfig()
            config.tools = [GenaiTool(function_declarations=declarations)]

        contents: list = list(history or [])
        if message:
            contents.append(Content(role="user", parts=[Part(text=message)]))

        resp = self._client.models.generate_content(
            model=model,
            contents=contents,
            config=config,
        )
        return _parse_response(resp)

    def user_turn(self, message: str) -> Content:
        from google.genai.types import Content, Part

        return Content(role="user", parts=[Part(text=message)])

    def tool_results_turn(self, outputs: list[tuple[ToolCall, str]]) -> list:
        """Typed function-response parts for the executed tool calls."""
        from google.genai.types import Content, FunctionResponse, Part

        return [
            Content(
                role="user",
                parts=[
                    Part(
                        function_response=FunctionResponse(
                            id=call.id, name=call.name, response={"result": output}
                        )
                    )
                    for call, output in outputs
                ],
            )
        ]