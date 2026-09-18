"""
Phase 9 — background thread for document ingestion.

Same reasoning as mic_worker.py/tts_worker.py: the first ingest in a
process loads a sentence-transformers model from disk (a couple seconds)
and then runs embedding + a Chroma upsert, none of which should happen on
the GUI thread. This worker calls rag.ingest_file() once and emits either
done_ready or error_occurred -- main.py's upload button owns everything
about what happens with the result (a transcript line for now).
"""

from PySide6.QtCore import QThread, Signal

from . import rag


class RagIngestWorker(QThread):
    """Runs one rag.ingest_file() call off the main/UI thread."""

    done_ready = Signal(str)
    error_occurred = Signal(str)

    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self._path = path

    def run(self):
        try:
            summary = rag.ingest_file(self._path)
        except RuntimeError as e:
            self.error_occurred.emit(str(e))
        except Exception as e:
            self.error_occurred.emit(f"Unexpected error: {e}")
        else:
            self.done_ready.emit(summary)
