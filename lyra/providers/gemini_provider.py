"""Gemini provider — wraps the `google-genai` SDK behind the LLMProvider interface."""

from typing import Any, Optional

from .base import LLMProvider, ToolEventCallback
from .registry import register_provider
from ..tools.base import ToolSpec
from ..tools.registry import get_tool


def _json_schema_to_gemini(schema: Any) -> Any:
    """
    Recursively upper-case JSON-Schema `type` values ("object" -> "OBJECT")
    so a ToolSpec's plain JSON-Schema `parameters` dict matches the shape
    google-genai's types.Schema expects. Every ToolSpec (tools/base.py) is
    written once as plain JSON Schema so it works for both Groq's
    OpenAI-style tool schema (lowercase, used as-is in groq_provider.py)
    and Gemini's Schema (uppercase) — this is the only place that
    difference is handled, so tool authors never have to think about it.
    """
    if not isinstance(schema, dict):
        return schema
    out = {}
    for key, value in schema.items():
        if key == "type" and isinstance(value, str):
            out[key] = value.upper()
        elif key == "properties" and isinstance(value, dict):
            out[key] = {k: _json_schema_to_gemini(v) for k, v in value.items()}
        elif key == "items":
            out[key] = _json_schema_to_gemini(value)
        else:
            out[key] = value
    return out


@register_provider("gemini")
class GeminiProvider(LLMProvider):
    def ask(self, prompt: str) -> str:
        from google import genai
        from google.genai import errors as genai_errors

        client = genai.Client(api_key=self.api_key)

        try:
            response = client.models.generate_content(
                model=self.model_name,
                contents=prompt,
            )
        except genai_errors.ClientError as e:
            if getattr(e, "code", None) == 429:
                raise RuntimeError(
                    "Rate limit hit (free tier). Wait a bit and try again."
                ) from e
            if getattr(e, "code", None) in (401, 403):
                raise RuntimeError(
                    "Gemini rejected the API key. Check your .env file."
                ) from e
            raise RuntimeError(f"Gemini rejected the request: {e}") from e
        except genai_errors.ServerError as e:
            raise RuntimeError(f"Gemini server error — try again shortly: {e}") from e
        except Exception as e:
            raise RuntimeError(f"Could not reach Gemini: {e}") from e

        text = getattr(response, "text", None)
        if not text:
            raise RuntimeError("Gemini returned an empty response.")
        return text

    def ask_stream(self, prompt: str):
        from google import genai
        from google.genai import errors as genai_errors

        client = genai.Client(api_key=self.api_key)

        try:
            stream = client.models.generate_content_stream(
                model=self.model_name,
                contents=prompt,
            )
            got_any = False
            for chunk in stream:
                text = getattr(chunk, "text", None)
                if text:
                    got_any = True
                    yield text
            if not got_any:
                raise RuntimeError("Gemini returned an empty response.")
        except genai_errors.ClientError as e:
            if getattr(e, "code", None) == 429:
                raise RuntimeError(
                    "Rate limit hit (free tier). Wait a bit and try again."
                ) from e
            if getattr(e, "code", None) in (401, 403):
                raise RuntimeError(
                    "Gemini rejected the API key. Check your .env file."
                ) from e
            raise RuntimeError(f"Gemini rejected the request: {e}") from e
        except genai_errors.ServerError as e:
            raise RuntimeError(f"Gemini server error — try again shortly: {e}") from e
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"Could not reach Gemini: {e}") from e

    def ask_with_tools(
        self,
        prompt: str,
        tools: list[ToolSpec],
        system_instruction: str = "",
        on_tool_event: Optional[ToolEventCallback] = None,
    ) -> str:
        from google import genai
        from google.genai import types
        from google.genai import errors as genai_errors

        client = genai.Client(api_key=self.api_key)

        function_declarations = [
            types.FunctionDeclaration(
                name=t.name,
                description=t.description,
                parameters=_json_schema_to_gemini(t.parameters),
            )
            for t in tools
        ]
        gemini_tools = [types.Tool(function_declarations=function_declarations)]

        config = types.GenerateContentConfig(
            tools=gemini_tools,
            system_instruction=system_instruction or None,
            # Manual function execution: Lyra runs each tool itself via
            # ToolSpec.func (so it can emit on_tool_event and enforce the
            # requires_confirmation guard below) instead of letting the SDK
            # auto-call a plain Python function on the model's behalf.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=True
            ),
        )

        contents = [types.Content(role="user", parts=[types.Part(text=prompt)])]

        def _call():
            try:
                return client.models.generate_content(
                    model=self.model_name,
                    contents=contents,
                    config=config,
                )
            except genai_errors.ClientError as e:
                if getattr(e, "code", None) == 429:
                    raise RuntimeError(
                        "Rate limit hit (free tier). Wait a bit and try again."
                    ) from e
                if getattr(e, "code", None) in (401, 403):
                    raise RuntimeError(
                        "Gemini rejected the API key. Check your .env file."
                    ) from e
                raise RuntimeError(f"Gemini rejected the request: {e}") from e
            except genai_errors.ServerError as e:
                raise RuntimeError(f"Gemini server error — try again shortly: {e}") from e
            except Exception as e:
                raise RuntimeError(f"Could not reach Gemini: {e}") from e

        response = _call()
        candidate = response.candidates[0] if response.candidates else None
        parts = candidate.content.parts if candidate and candidate.content else []
        function_calls = [
            p.function_call for p in parts if getattr(p, "function_call", None)
        ]

        if not function_calls:
            text = getattr(response, "text", None)
            if not text:
                raise RuntimeError("Gemini returned an empty response.")
            return text

        # Phase 4 is a single round (see LLMProvider.ask_with_tools's
        # docstring): execute every tool call the model asked for, feed all
        # results back, then ask once more for the final answer.
        contents.append(candidate.content)

        function_response_parts = []
        for fc in function_calls:
            tool_name = fc.name
            args = dict(fc.args) if fc.args else {}

            try:
                tool = get_tool(tool_name)
            except RuntimeError as e:
                result_text = f"Error: {e}"
                if on_tool_event:
                    on_tool_event(
                        {"type": "tool_error", "name": tool_name, "error": str(e)}
                    )
                function_response_parts.append(
                    types.Part.from_function_response(
                        name=tool_name, response={"error": result_text}
                    )
                )
                continue

            if on_tool_event:
                on_tool_event({"type": "tool_call", "name": tool_name, "args": args})

            # Security rule #3: a sensitive tool never runs itself just
            # because the model asked for it. Phase 4 has no confirmation
            # UI yet, so the safe default is to refuse and say so, rather
            # than silently executing or silently ignoring the request.
            if tool.requires_confirmation:
                result_text = (
                    f"Tool '{tool_name}' requires user confirmation before it "
                    "can run, which isn't wired up yet — it was not executed."
                )
                if on_tool_event:
                    on_tool_event(
                        {"type": "tool_blocked", "name": tool_name, "args": args}
                    )
            else:
                try:
                    result_text = tool.func(**args)
                except Exception as e:
                    result_text = f"Error: {e}"
                    if on_tool_event:
                        on_tool_event(
                            {"type": "tool_error", "name": tool_name, "error": str(e)}
                        )
                else:
                    if on_tool_event:
                        on_tool_event(
                            {
                                "type": "tool_result",
                                "name": tool_name,
                                "result": result_text,
                            }
                        )

            function_response_parts.append(
                types.Part.from_function_response(
                    name=tool_name, response={"result": result_text}
                )
            )

        contents.append(types.Content(role="user", parts=function_response_parts))

        final_response = _call()
        final_text = getattr(final_response, "text", None)
        if not final_text:
            raise RuntimeError("Gemini returned an empty response after the tool call.")
        return final_text
