"""
Phase 3 — background thread for speaking a reply aloud.

Same pattern as worker.py / mic_worker.py: tts.speak() blocks for as long
as the speech takes, so it runs on its own QThread rather than the GUI
thread. Emits finished (via QThread's own built-in signal) and
error_occurred if the OS TTS engine fails.
"""

from PySide6.QtCore import QThread, Signal

from .tts import speak


class TTSWorker(QThread):
    """Runs one speak() call off the main/UI thread."""

    error_occurred = Signal(str)

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self._text = text

    def run(self):
        try:
            speak(self._text)
        except RuntimeError as e:
            self.error_occurred.emit(str(e))
        except Exception as e:
            self.error_occurred.emit(f"Unexpected error: {e}")
