"""Groq provider — wraps the `groq` SDK behind the LLMProvider interface."""

import json
from typing import Callable, Optional

from .base import LLMProvider, ToolEventCallback
from .registry import register_provider
from ..config import MAX_TOOL_ROUNDS
from ..tools.base import ToolSpec
from ..tools.registry import get_tool


@register_provider("groq")
class GroqProvider(LLMProvider):
    def ask(self, prompt: str) -> str:
        from groq import Groq
        import groq as groq_sdk

        client = Groq(api_key=self.api_key)

        try:
            response = client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": prompt}],
            )
        except groq_sdk.RateLimitError as e:
            raise RuntimeError(
                "Rate limit hit (free tier). Wait a bit and try again."
            ) from e
        except groq_sdk.AuthenticationError as e:
            raise RuntimeError(
                "Groq rejected the API key. Check your .env file."
            ) from e
        except groq_sdk.APIStatusError as e:
            raise RuntimeError(f"Groq rejected the request: {e}") from e
        except Exception as e:
            raise RuntimeError(f"Could not reach Groq: {e}") from e

        text = response.choices[0].message.content
        if not text:
            raise RuntimeError("Groq returned an empty response.")
        return text

    def ask_stream(self, prompt: str):
        from groq import Groq
        import groq as groq_sdk

        client = Groq(api_key=self.api_key)

        try:
            stream = client.chat.completions.create(
                model=self.model_name,
                messages=[{"role": "user", "content": prompt}],
                stream=True,
            )
            got_any = False
            for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    got_any = True
                    yield delta
            if not got_any:
                raise RuntimeError("Groq returned an empty response.")
        except groq_sdk.RateLimitError as e:
            raise RuntimeError(
                "Rate limit hit (free tier). Wait a bit and try again."
            ) from e
        except groq_sdk.AuthenticationError as e:
            raise RuntimeError(
                "Groq rejected the API key. Check your .env file."
            ) from e
        except groq_sdk.APIStatusError as e:
            raise RuntimeError(f"Groq rejected the request: {e}") from e
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"Could not reach Groq: {e}") from e

    def ask_with_tools(
        self,
        prompt: str,
        tools: list[ToolSpec],
        system_instruction: str = "",
        on_tool_event: Optional[ToolEventCallback] = None,
        on_chunk: Optional[Callable[[str], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> str:
        from groq import Groq
        import groq as groq_sdk

        client = Groq(api_key=self.api_key)

        # Groq's chat completions API is OpenAI-compatible: a "tool" schema
        # per function, and (after a call) a "tool" role message per result.
        tool_schemas = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in tools
        ]

        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})

        def _map_error(e: Exception) -> RuntimeError:
            if isinstance(e, groq_sdk.RateLimitError):
                return RuntimeError("Rate limit hit (free tier). Wait a bit and try again.")
            if isinstance(e, groq_sdk.AuthenticationError):
                return RuntimeError("Groq rejected the API key. Check your .env file.")
            if isinstance(e, groq_sdk.APIStatusError):
                return RuntimeError(f"Groq rejected the request: {e}")
            return RuntimeError(f"Could not reach Groq: {e}")

        def _stream_call(with_tools: bool):
            """stream=True is what actually gets real, incremental output out
            of Groq instead of one blocking call that only returns once the
            whole answer is generated — this is the fix for the "all at once"
            symptom, on the SDK-call side of it."""
            try:
                return client.chat.completions.create(
                    model=self.model_name,
                    messages=messages,
                    tools=tool_schemas if with_tools else None,
                    tool_choice="auto" if with_tools else "none",
                    stream=True,
                )
            except Exception as e:
                raise _map_error(e) from e

        def _consume(stream):
            """Drain one OpenAI-compatible streaming response, forwarding
            content deltas to on_chunk the instant each arrives, and
            reassembling any tool_calls out of their streamed fragments
            (a tool call's arguments string is itself split across many
            chunks, indexed by tc.index, per Groq/OpenAI's streaming
            tool-call format). Returns (text, tool_calls)."""
            text_parts = []
            pending_calls = {}
            try:
                for piece in stream:
                    if should_cancel and should_cancel():
                        close = getattr(stream, "close", None)
                        if close:
                            try:
                                close()
                            except Exception:
                                pass
                        break
                    delta = piece.choices[0].delta
                    if delta.content:
                        text_parts.append(delta.content)
                        if on_chunk:
                            on_chunk(delta.content)
                    for tc in (delta.tool_calls or []):
                        slot = pending_calls.setdefault(
                            tc.index, {"id": None, "name": None, "arguments": ""}
                        )
                        if tc.id:
                            slot["id"] = tc.id
                        if tc.function and tc.function.name:
                            slot["name"] = tc.function.name
                        if tc.function and tc.function.arguments:
                            slot["arguments"] += tc.function.arguments
            except Exception as e:
                raise _map_error(e) from e

            ordered_calls = [pending_calls[i] for i in sorted(pending_calls)]
            return "".join(text_parts), ordered_calls

        def _execute_tool_calls(assistant_text, tool_calls):
            """Run every tool call in `tool_calls`, appending the assistant's
            tool_calls message and each tool result message to `messages`
            in place. One round of the Phase 6 chain below."""
            messages.append(
                {
                    "role": "assistant",
                    "content": assistant_text or None,
                    "tool_calls": [
                        {
                            "id": call["id"],
                            "type": "function",
                            "function": {"name": call["name"], "arguments": call["arguments"]},
                        }
                        for call in tool_calls
                    ],
                }
            )

            for call in tool_calls:
                tool_name = call["name"]
                try:
                    args = json.loads(call["arguments"] or "{}")
                except json.JSONDecodeError as e:
                    result_text = f"Error: could not parse arguments — {e}"
                    if on_tool_event:
                        on_tool_event({"type": "tool_error", "name": tool_name, "error": result_text})
                else:
                    if on_tool_event:
                        on_tool_event({"type": "tool_call", "name": tool_name, "args": args})
                    try:
                        tool = get_tool(tool_name)
                    except Exception as e:
                        result_text = f"Error: {e}"
                        if on_tool_event:
                            on_tool_event({"type": "tool_error", "name": tool_name, "error": str(e)})
                    else:
                        # Security rule #3: a sensitive tool never runs itself
                        # just because the model asked for it. No confirmation
                        # UI exists yet, so the safe default is to refuse and
                        # say so, rather than silently executing.
                        if tool.requires_confirmation:
                            result_text = (
                                f"Tool '{tool_name}' requires user confirmation before "
                                "it can run, which isn't wired up yet — it was not executed."
                            )
                            if on_tool_event:
                                on_tool_event({"type": "tool_blocked", "name": tool_name, "args": args})
                        else:
                            try:
                                result_text = tool.func(**args)
                            except Exception as e:
                                result_text = f"Error: {e}"
                                if on_tool_event:
                                    on_tool_event({"type": "tool_error", "name": tool_name, "error": str(e)})
                            else:
                                if on_tool_event:
                                    on_tool_event({"type": "tool_result", "name": tool_name, "result": result_text})

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "name": tool_name,
                        "content": result_text,
                    }
                )

        # Phase 6 — multi-step tool chains: keep letting the model call tools,
        # feed results back, and ask again (still offering tools) for up to
        # MAX_TOOL_ROUNDS rounds, so it can chain several calls together
        # (e.g. search, then compute on what it found) instead of being
        # limited to one round. The loop's `else` (only reached if it never
        # `break`s, i.e. every round kept requesting more tools) forces a
        # final tools-off call so a runaway chain can't hang the request.
        final_text = None
        for _round in range(MAX_TOOL_ROUNDS):
            text, tool_calls = _consume(_stream_call(with_tools=True))

            if not tool_calls:
                final_text = text
                break

            if should_cancel and should_cancel():
                return text  # cancelled before this round's tools ran

            _execute_tool_calls(text, tool_calls)

            if should_cancel and should_cancel():
                return text  # cancelled after tools ran, before asking again
        else:
            if on_tool_event:
                on_tool_event({"type": "round_limit", "rounds": MAX_TOOL_ROUNDS})
            final_text, _ = _consume(_stream_call(with_tools=False))

        if not final_text:
            raise RuntimeError("Groq returned an empty response.")
        return final_text
