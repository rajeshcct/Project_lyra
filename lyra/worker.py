"""
Phase 2 — background thread for the LLM call.

Keeping the API call off the GUI thread is non-negotiable per the plan:
"Use QThread from the start — don't let the window freeze." This worker
is intentionally dumb: it takes one prompt, calls llm_client.ask_llm_stream,
and emits a chunk_ready signal per piece of text as it streams in, plus an
error_occurred signal if anything goes wrong. All GUI logic stays in main.py.

This class has no idea which provider is behind ask_llm_stream — Groq,
Gemini, or whatever gets added next — that's the whole point of the
provider abstraction in providers/.
"""

from PySide6.QtCore import QThread, Signal

from .llm_client import ask_llm_stream, ask_llm_with_tools


class LLMWorker(QThread):
    """Runs one ask_llm_stream() call off the main/UI thread."""

    chunk_ready = Signal(str)
    error_occurred = Signal(str)

    def __init__(self, prompt: str, parent=None):
        super().__init__(parent)
        self._prompt = prompt

    def run(self):
        try:
            for chunk in ask_llm_stream(self._prompt):
                self.chunk_ready.emit(chunk)
        except RuntimeError as e:
            self.error_occurred.emit(str(e))
        except Exception as e:
            # belt-and-suspenders — never let the thread die silently
            self.error_occurred.emit(f"Unexpected error: {e}")


class ToolWorker(QThread):
    """
    Phase 4 — background thread for a tool-enabled LLM call.

    Same off-the-GUI-thread reasoning as LLMWorker, and wraps
    llm_client.ask_llm_with_tools instead of ask_llm_stream. The
    tool-decision step itself still can't be streamed token-by-token (the
    model has to finish deciding whether to call a tool before any answer
    text exists at all — see LLMProvider.ask_with_tools's docstring), but
    the actual answer text -- whether it's a direct reply or the follow-up
    after a tool runs -- streams in normally. So this emits:

      - tool_event, once per tool call/result/error, live as they happen
        (drives the UI's reasoning-trace panel while the request is still
        in flight instead of leaving the user staring at a blank wait)
      - chunk_ready, once per piece of real answer text as it streams in
        (drives the reply bubble growing live, the same way LLMWorker's
        chunk_ready does for the plain non-tool path)
      - reply_ready, once, with the complete final answer text (used for
        memory/TTS bookkeeping once the turn is over, not for display --
        the bubble is already fully built by the time this fires)

    tool_event/chunk_ready are emitted from this thread; Qt queues the
    delivery to the connected slot on the main thread automatically (default
    AutoConnection behaves as QueuedConnection across threads), so no manual
    thread-safety handling is needed on the receiving end in main.py.
    """

    tool_event = Signal(dict)
    chunk_ready = Signal(str)
    reply_ready = Signal(str)
    error_occurred = Signal(str)

    def __init__(self, prompt: str, parent=None):
        super().__init__(parent)
        self._prompt = prompt
        self._cancelled = False

    def cancel(self):
        """Ask the in-flight request to stop at the next streamed chunk.
        Cooperative, not forced: run() keeps executing until
        ask_llm_with_tools notices should_cancel() and returns, so this
        never leaves the underlying HTTP stream/connection in a half-torn
        state the way QThread.terminate() would."""
        self._cancelled = True

    def run(self):
        try:
            reply = ask_llm_with_tools(
                self._prompt,
                on_tool_event=self.tool_event.emit,
                on_chunk=self.chunk_ready.emit,
                should_cancel=lambda: self._cancelled,
            )
            self.reply_ready.emit(reply)
        except RuntimeError as e:
            self.error_occurred.emit(str(e))
        except Exception as e:
            self.error_occurred.emit(f"Unexpected error: {e}")
