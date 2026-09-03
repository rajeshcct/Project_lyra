"""
Common contract every LLM provider must implement.

Any new provider — Groq, Gemini, OpenAI, a local model, whatever — is just a
class in this package that subclasses LLMProvider and implements ask().
Nothing outside providers/ ever imports a provider-specific SDK directly.
"""

from abc import ABC, abstractmethod
from typing import Callable, Optional

from ..tools.base import ToolSpec

# One tool-call/tool-result event, handed to on_tool_event as it happens so
# the UI's reasoning-trace panel can show it live. Shape:
#   {"type": "tool_call", "name": str, "args": dict}
#   {"type": "tool_result", "name": str, "result": str}
#   {"type": "tool_error", "name": str, "error": str}
ToolEventCallback = Callable[[dict], None]


class LLMProvider(ABC):
    """One provider = one API key + one model + one ask() implementation."""

    def __init__(self, api_key: str, model_name: str):
        self.api_key = api_key
        self.model_name = model_name

    @abstractmethod
    def ask(self, prompt: str) -> str:
        """
        Send `prompt` to this provider and return the reply text.

        Implementations MUST catch their SDK's own exceptions and re-raise
        as RuntimeError with a short, human-readable message — callers
        (the CLI in test_llm.py, the QThread in worker.py) only ever catch
        RuntimeError and show str(e) directly in the UI.
        """
        raise NotImplementedError

    @abstractmethod
    def ask_stream(self, prompt: str):
        """
        Send `prompt` to this provider and yield reply text chunks as they
        arrive, instead of blocking for the full reply.

        Same RuntimeError contract as ask(): implementations MUST catch
        their SDK's own exceptions (including ones raised mid-stream) and
        re-raise as RuntimeError. Callers only ever catch RuntimeError.
        """
        raise NotImplementedError

    @abstractmethod
    def ask_with_tools(
        self,
        prompt: str,
        tools: list[ToolSpec],
        system_instruction: str = "",
        on_tool_event: Optional[ToolEventCallback] = None,
        on_chunk: Optional[Callable[[str], None]] = None,
        should_cancel: Optional[Callable[[], bool]] = None,
    ) -> str:
        """
        Send `prompt` to this provider with `tools` available for it to call,
        via whichever native function-calling mechanism this provider's SDK
        offers. Returns the final natural-language answer text.

        Phase 6 scope: if the model requests one or more tool calls, each is
        executed locally via its ToolSpec.func, results are fed back to the
        model, and the model is asked again -- with tools still on offer --
        so it can chain further calls (e.g. look something up, then act on
        what it found) instead of being limited to one round. This repeats
        until the model responds with no further tool calls, or until
        config.MAX_TOOL_ROUNDS rounds have been spent, at which point tools
        are switched off for one last call so the model is forced to give a
        text answer using whatever it's already gathered rather than the
        request hanging indefinitely.

        `on_tool_event`, if given, is called synchronously for every tool
        call and result/error as they happen — implementations call it from
        whatever thread ask_with_tools() itself runs on (see worker.py for
        how the GUI turns this into a live reasoning-trace display).

        `on_chunk`, if given, is called once per piece of real answer text as
        it streams in from the provider's own streaming API (true token/delta
        streaming — never a whole reply chopped up after the fact). It fires
        for a direct answer with no tool call, and for the follow-up answer
        generated after a tool call's results are fed back. Nothing streams
        during the tool-decision step itself, since no answer text exists
        until the model has finished deciding whether/which tool to call —
        this matches how OpenAI/Groq-style streaming tool-calls behave
        natively, it isn't something Lyra is choosing to hold back.

        `should_cancel`, if given, is polled between streamed pieces; once it
        returns True the implementation stops consuming the stream (closing
        the underlying HTTP stream where the SDK exposes a way to) and
        returns whatever text was produced so far instead of raising.

        `system_instruction`, if given, is sent as an actual system-level
        instruction via this provider's native mechanism for that (not
        concatenated into the user prompt) — used for the tool-safety rule
        that tool results are data, never instructions to follow.

        Same RuntimeError contract as ask()/ask_stream(): implementations
        MUST catch their SDK's own exceptions and re-raise as RuntimeError.
        """
        raise NotImplementedError
