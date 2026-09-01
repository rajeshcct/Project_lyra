"""
Phase 3 — background thread for mic capture.

Same pattern as worker.py's LLMWorker: mic capture (and the recognition
API round-trip inside it) must never run on the GUI thread, or the window
freezes exactly the way it would during an un-threaded LLM call. This
worker is intentionally dumb -- it calls stt.listen_once() once and emits
either text_ready or error_occurred. All GUI logic (what happens with the
recognized text) stays in main.py.
"""

from PySide6.QtCore import QThread, Signal

from .stt import listen_once


class MicWorker(QThread):
    """Runs one listen_once() call off the main/UI thread."""

    text_ready = Signal(str)
    error_occurred = Signal(str)

    def run(self):
        try:
            text = listen_once()
        except RuntimeError as e:
            self.error_occurred.emit(str(e))
        except Exception as e:
            # belt-and-suspenders — never let the thread die silently
            self.error_occurred.emit(f"Unexpected error: {e}")
        else:
            self.text_ready.emit(text)
