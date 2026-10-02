"""The bare tool loop — full-capability path over litellm.

Used by ``BareBackend`` for any spec the chat-only agent can't serve: tools,
structured output, multimodal input, knowledge, or a non-Google provider
(ollama/passthrough). Pure chat specs go to ``agent.MyAgent`` instead.

Model mapping: ``google`` -> ``gemini/<id>``, ``ollama`` -> ``ollama/<id>``
(any other provider string is passed through as-is, e.g. ``openai/gpt-4o``).
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from semente.backends.base import AgentInput, AgentSpec, AgentTurn
from semente.backends.toolkit import (
    StateContext,
    expand_tools,
    new_media_bag,
    run_tool,
    tool_schema,
)
from semente.configs.config import config

_MAX_TOOL_ITERATIONS = 10  # ponytail: cap the loop; raise if a domain needs more

_MIME_BY_EXT = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
    ".wav": "audio/wav", ".mp3": "audio/mpeg", ".ogg": "audio/ogg", ".mp4": "video/mp4",
}


def _image_data_url(img) -> str | None:
    if img.content:
        return f"data:{img.mime_type or 'image/png'};base64,{base64.b64encode(img.content).decode()}"
    if img.url:
        return img.url
    if img.filepath:
        p = Path(img.filepath)
        mime = img.mime_type or _MIME_BY_EXT.get(p.suffix.lower(), "image/png")
        return f"data:{mime};base64,{base64.b64encode(p.read_bytes()).decode()}"
    return None


def _audio_part(aud) -> dict | None:
    if aud.content:
        data = base64.b64encode(aud.content).decode()
        fmt = (aud.format or (aud.mime_type or "wav").split("/")[-1] or "wav")
        return {"type": "input_audio", "input_audio": {"data": data, "format": fmt}}
    if aud.filepath:
        p = Path(aud.filepath)
        data = base64.b64encode(p.read_bytes()).decode()
        fmt = aud.format or p.suffix.lstrip(".") or "wav"
        return {"type": "input_audio", "input_audio": {"data": data, "format": fmt}}
    return None


def _parse_json(text: str) -> dict | None:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


class BareAgentAdapter:
    """One LLM loop with tools, structured output, and multimodal input."""

    def __init__(self, spec: AgentSpec):
        self.spec = spec

    def _resolve_tools(self, ctx: StateContext) -> list:
        tools_or_callable = self.spec.tools
        if callable(tools_or_callable) and not isinstance(tools_or_callable, list):
            try:
                raw = tools_or_callable(ctx)
            except TypeError:
                raw = tools_or_callable()
        else:
            raw = tools_or_callable or []
        return expand_tools(list(raw))

    def _model(self) -> tuple[str, dict]:
        spec_model = self.spec.model
        provider = spec_model.provider if spec_model else config.PRIMARY_MODEL_PROVIDER
        model_id = spec_model.model_id if spec_model else config.PRIMARY_MODEL_ID

        if provider == "google":
            return f"gemini/{model_id}", {"api_key": config.GOOGLE_API_KEY}
        if provider == "ollama":
            return f"ollama/{model_id}", {
                "api_key": config.OLLAMA_API_KEY,
                "api_base": config.OLLAMA_HOST,
            }
        return model_id, {}

    def _user_message(self, input: AgentInput) -> dict:
        content: list = []
        if input.text:
            content.append({"type": "text", "text": input.text})
        for img in input.images or []:
            url = _image_data_url(img)
            if url:
                content.append({"type": "image_url", "image_url": {"url": url}})
        for aud in input.audio or []:
            part = _audio_part(aud)
            if part:
                content.append(part)
        if not content:
            content.append({"type": "text", "text": ""})
        if len(content) == 1 and content[0]["type"] == "text":
            return {"role": "user", "content": content[0]["text"]}
        return {"role": "user", "content": content}

    def run(self, input: AgentInput) -> AgentTurn:
        import litellm

        state = input.session_state if input.session_state is not None else {}
        # One context for the whole run: state by reference (tool mutations
        # persist) + the real user_id (tools read run_context.user_id).
        ctx = StateContext(state, input.user_id)
        media_bag = new_media_bag()
        input_files = list(input.files or [])

        tools = self._resolve_tools(ctx)
        if self.spec.knowledge is not None:
            from semente.knowledge import SEARCH_KNOWLEDGE_INSTRUCTIONS, build_search_tool

            tools.append(build_search_tool(self.spec.knowledge))

        instruction = self.spec.instructions
        system = instruction(ctx) if callable(instruction) else str(instruction)
        if self.spec.knowledge is not None:
            from semente.knowledge import SEARCH_KNOWLEDGE_INSTRUCTIONS

            system += "\n\n<knowledge_base>\n" + SEARCH_KNOWLEDGE_INSTRUCTIONS + "\n</knowledge_base>"

        messages: list = [{"role": "system", "content": system}, self._user_message(input)]

        tool_schemas = [{"type": "function", "function": tool_schema(t)} for t in tools]
        tool_by_name = {tool_schema(t)["name"]: t for t in tools}

        model, kwargs = self._model()

        final_text = ""
        for _ in range(_MAX_TOOL_ITERATIONS):
            resp = litellm.completion(
                model=model,
                messages=messages,
                tools=tool_schemas or None,
                **kwargs,
            )
            msg = resp.choices[0].message

            if getattr(msg, "tool_calls", None):
                messages.append(
                    {
                        "role": "assistant",
                        "content": msg.content or "",
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.function.name,
                                    "arguments": tc.function.arguments,
                                },
                            }
                            for tc in msg.tool_calls
                        ],
                    }
                )
                for tc in msg.tool_calls:
                    name = tc.function.name
                    try:
                        args = json.loads(tc.function.arguments or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    tool = tool_by_name.get(name)
                    result_text = (
                        run_tool(tool, args, ctx, media_bag, input_files=input_files)
                        if tool is not None
                        else f"Unknown tool: {name}"
                    )
                    messages.append(
                        {"role": "tool", "tool_call_id": tc.id, "content": result_text}
                    )
            else:
                final_text = msg.content or ""
                break

        structured = _parse_json(final_text) if self.spec.output_schema and final_text else None

        return AgentTurn(
            content=final_text,
            structured=structured,
            images=media_bag["images"] or None,
            videos=media_bag["videos"] or None,
            audio=media_bag["audios"] or None,
            files=media_bag["files"] or None,
        )