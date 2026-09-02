"""Groq provider — wraps the `groq` SDK behind the LLMProvider interface."""

import json
from typing import Optional

from .base import LLMProvider, ToolEventCallback
from .registry import register_provider
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

        def _call(with_tools: bool):
            try:
                return client.chat.completions.create(
                    model=self.model_name,
                    messages=messages,
                    tools=tool_schemas if with_tools else None,
                    tool_choice="auto" if with_tools else None,
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

        response = _call(with_tools=True)
        message = response.choices[0].message
        tool_calls = getattr(message, "tool_calls", None)

        if not tool_calls:
            text = message.content
            if not text:
                raise RuntimeError("Groq returned an empty response.")
            return text

        # Phase 4 is a single round: execute every tool call the model asked
        # for, feed all the results back, then ask once more for the final
        # answer. (Multi-round chaining is Phase 6.)
        messages.append(message.model_dump(exclude_none=True))

        for call in tool_calls:
            tool_name = call.function.name
            try:
                args = json.loads(call.function.arguments or "{}")
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
                    # just because the model asked for it. Phase 4 has no
                    # confirmation UI yet, so the safe default is to refuse
                    # and say so, rather than silently executing.
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
                    "tool_call_id": call.id,
                    "name": tool_name,
                    "content": result_text,
                }
            )

        final_response = _call(with_tools=False)
        final_text = final_response.choices[0].message.content
        if not final_text:
            raise RuntimeError("Groq returned an empty response after the tool call.")
        return final_text
