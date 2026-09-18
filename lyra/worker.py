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

import threading

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
    # Phase 7 -- emitted from this (background) thread, auto-queued by Qt
    # onto the main thread same as tool_event/chunk_ready above. Carries
    # (tool_name, args) for a tool with ToolSpec.requires_confirmation set;
    # main.py's slot shows a dialog and calls provide_confirmation() with
    # the human's answer, which is what actually unblocks run() below.
    confirmation_requested = Signal(str, dict)

    def __init__(self, prompt: str, parent=None):
        super().__init__(parent)
        self._prompt = prompt
        self._cancelled = False
        # Phase 7 -- confirmation bridge. _on_confirmation_required() below
        # runs on THIS (background) thread inside ask_llm_with_tools and must
        # block until a human answers; a plain Python threading.Event (not a
        # Qt primitive) is what it waits on, since Qt signals themselves
        # don't have a synchronous "wait for the slot's return value" mode
        # across threads -- the slot in main.py answers by calling
        # provide_confirmation(), which stashes the result and sets the event.
        self._confirmation_event = threading.Event()
        self._confirmation_result = False

    def cancel(self):
        """Ask the in-flight request to stop at the next streamed chunk.
        Cooperative, not forced: run() keeps executing until
        ask_llm_with_tools notices should_cancel() and returns, so this
        never leaves the underlying HTTP stream/connection in a half-torn
        state the way QThread.terminate() would. Also unblocks a pending
        confirmation wait (treated as a decline) so Stop can't be swallowed
        by a dialog nobody answers."""
        self._cancelled = True
        self._confirmation_result = False
        self._confirmation_event.set()

    def provide_confirmation(self, approved: bool):
        """Called from the MAIN thread (main.py's dialog slot) once the user
        has answered. Unblocks whichever _on_confirmation_required() call is
        currently waiting in run()'s thread."""
        self._confirmation_result = approved
        self._confirmation_event.set()

    def _on_confirmation_required(self, tool_name: str, args: dict) -> bool:
        """Passed to ask_llm_with_tools as on_confirmation_required. Runs on
        this QThread, not the GUI thread -- emitting a signal here is safe
        and gets auto-queued to the main thread's event loop (Qt's default
        AutoConnection), but the return value has to come back some other
        way, hence the Event/provide_confirmation() pair above."""
        self._confirmation_event.clear()
        self.confirmation_requested.emit(tool_name, args)
        # Poll instead of a bare wait() so an in-flight cancel() (set from
        # the main thread while a dialog is up) is noticed promptly rather
        # than only after the user eventually answers.
        while not self._confirmation_event.wait(timeout=0.2):
            if self._cancelled:
                return False
        return self._confirmation_result

    def run(self):
        try:
            reply = ask_llm_with_tools(
                self._prompt,
                on_tool_event=self.tool_event.emit,
                on_chunk=self.chunk_ready.emit,
                should_cancel=lambda: self._cancelled,
                on_confirmation_required=self._on_confirmation_required,
            )
            self.reply_ready.emit(reply)
        except RuntimeError as e:
            self.error_occurred.emit(str(e))
        except Exception as e:
            self.error_occurred.emit(f"Unexpected error: {e}")
