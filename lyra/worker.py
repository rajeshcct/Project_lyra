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

from .llm_client import ask_llm_stream


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
