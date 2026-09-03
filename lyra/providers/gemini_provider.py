"""Gemini provider — wraps the `google-genai` SDK behind the LLMProvider interface."""

from typing import Any, Callable, Optional

from .base import LLMProvider, ToolEventCallback
from .registry import register_provider
from ..config import MAX_TOOL_ROUNDS
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
        on_chunk: Optional[Callable[[str], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
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

        # Manual function execution: Lyra runs each tool itself via
        # ToolSpec.func (so it can emit on_tool_event and enforce the
        # requires_confirmation guard below) instead of letting the SDK
        # auto-call a plain Python function on the model's behalf.
        _afc_disabled = types.AutomaticFunctionCallingConfig(disable=True)
        config_with_tools = types.GenerateContentConfig(
            tools=gemini_tools,
            system_instruction=system_instruction or None,
            automatic_function_calling=_afc_disabled,
        )
        # Phase 6: tools-off config used to force a final text answer once
        # MAX_TOOL_ROUNDS has been spent (see the loop below) — Gemini has
        # no separate tool_choice="none" flag the way Groq/OpenAI do, so the
        # way to stop it calling a function is to not offer any this round.
        config_no_tools = types.GenerateContentConfig(
            system_instruction=system_instruction or None,
            automatic_function_calling=_afc_disabled,
        )

        contents = [types.Content(role="user", parts=[types.Part(text=prompt)])]

        def _map_error(e: Exception) -> RuntimeError:
            if isinstance(e, genai_errors.ClientError):
                if getattr(e, "code", None) == 429:
                    return RuntimeError("Rate limit hit (free tier). Wait a bit and try again.")
                if getattr(e, "code", None) in (401, 403):
                    return RuntimeError("Gemini rejected the API key. Check your .env file.")
                return RuntimeError(f"Gemini rejected the request: {e}")
            if isinstance(e, genai_errors.ServerError):
                return RuntimeError(f"Gemini server error — try again shortly: {e}")
            return RuntimeError(f"Could not reach Gemini: {e}")

        def _stream_call(with_tools: bool = True):
            """generate_content_stream is what actually gets real, incremental
            output out of Gemini instead of one blocking call that only
            returns once the whole answer is generated."""
            try:
                return client.models.generate_content_stream(
                    model=self.model_name,
                    contents=contents,
                    config=config_with_tools if with_tools else config_no_tools,
                )
            except Exception as e:
                raise _map_error(e) from e

        def _consume(stream):
            """Drain one Gemini stream, forwarding text parts to on_chunk the
            instant each arrives. Also collects every part (text and
            function_call alike) so the model's turn can be replayed back to
            it verbatim as conversation history if a tool call follows.
            Returns (text, function_calls, collected_parts)."""
            text_parts = []
            function_calls = []
            collected_parts = []
            try:
                for chunk in stream:
                    if should_cancel and should_cancel():
                        close = getattr(stream, "close", None)
                        if close:
                            try:
                                close()
                            except Exception:
                                pass
                        break
                    candidate = chunk.candidates[0] if chunk.candidates else None
                    if not candidate or not candidate.content:
                        continue
                    for part in candidate.content.parts or []:
                        collected_parts.append(part)
                        text = getattr(part, "text", None)
                        if text:
                            text_parts.append(text)
                            if on_chunk:
                                on_chunk(text)
                        if getattr(part, "function_call", None):
                            function_calls.append(part.function_call)
            except Exception as e:
                raise _map_error(e) from e

            return "".join(text_parts), function_calls, collected_parts

        def _execute_function_calls(function_calls, collected_parts):
            """Run every call in `function_calls`, appending the model's turn
            and a function-response turn to `contents` in place. One round
            of the Phase 6 chain below."""
            contents.append(types.Content(role="model", parts=collected_parts))

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
                # because the model asked for it. No confirmation UI exists
                # yet, so the safe default is to refuse and say so, rather
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

        # Phase 6 — multi-step tool chains: keep letting the model call
        # functions, feed results back, and ask again (tools still on offer)
        # for up to MAX_TOOL_ROUNDS rounds, so it can chain several calls
        # together instead of being limited to one round. The loop's `else`
        # (reached only if it never `break`s, i.e. every round kept
        # requesting more calls) forces a final tools-off call so a runaway
        # chain can't hang the request.
        final_text = None
        for _round in range(MAX_TOOL_ROUNDS):
            text, function_calls, collected_parts = _consume(_stream_call(with_tools=True))

            if not function_calls:
                final_text = text
                break

            if should_cancel and should_cancel():
                return text  # cancelled before this round's tools ran

            _execute_function_calls(function_calls, collected_parts)

            if should_cancel and should_cancel():
                return text  # cancelled after tools ran, before asking again
        else:
            if on_tool_event:
                on_tool_event({"type": "round_limit", "rounds": MAX_TOOL_ROUNDS})
            final_text, _, _ = _consume(_stream_call(with_tools=False))

        if not final_text:
            raise RuntimeError("Gemini returned an empty response.")
        return final_text
