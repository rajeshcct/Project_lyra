"""
Phase 2 — Minimal Working Chat UI

Entry point for the GUI. Wires a bare PySide6 window to Phase 1's
llm_client.ask_llm function via a background QThread (worker.py), so the
window never freezes while waiting on the API. Which provider actually
answers (Groq, Gemini, ...) is whatever LLM_PROVIDER is set to in .env —
this file doesn't know or care.

Visuals live in their own modules, same "swap without touching other
files" principle as providers/:
    theme.py           - color palette + stylesheet (QSS)
    splash.py           - startup splash screen (assets/splash.png, fade-in)
    hud_background.py    - animated background painted behind the chat UI

Run:
    python main.py

Checkpoint this satisfies: typed text -> LLM reply appears in the window,
UI never freezes.
"""

import sys

from PySide6.QtCore import (
    QRect,
    QTimer,
    QPropertyAnimation,
    QParallelAnimationGroup,
    QEasingCurve,
)
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QStackedLayout,
    QScrollArea,
    QFrame,
    QLineEdit,
    QPushButton,
    QLabel,
    QGraphicsDropShadowEffect,
)

from config import PROVIDER
from worker import LLMWorker
from theme import QSS, ACCENT
from splash import SplashScreen
from hud_background import HudBackground
from chat_bubble import make_row


class ChatWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Lyra — Phase 2 Chat ({PROVIDER})")
        self.resize(720, 560)

        self._worker = None  # keep a reference so QThread isn't garbage collected mid-run
        self._current_reply_bubble = None  # the bubble currently being grown by a streaming reply

        # Streaming can arrive far faster than the UI can usefully redraw
        # (some providers push 100+ chunks/sec) -- if each chunk triggered
        # its own bubble resize + relayout immediately, a fast reply could
        # flood the event queue faster than the window can drain it, which
        # is what "not responding" actually was. Buffering chunks and
        # flushing them to the bubble on a fixed timer instead caps UI
        # updates at a steady ~25/sec no matter how fast tokens arrive.
        self._pending_chunk_text = ""
        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(40)
        self._flush_timer.timeout.connect(self._flush_pending_chunk)

        self._build_ui()

    def _build_ui(self):
        # Layer 0: animated HUD background (hud_background.py).
        # Layer 1: the actual chat UI, on a transparent widget so the
        # background shows through everywhere except the panels that
        # have their own semi-opaque QSS background (transcript, input).
        stack = QStackedLayout(self)
        stack.setStackingMode(QStackedLayout.StackAll)

        background = HudBackground(self)
        stack.addWidget(background)

        foreground = QWidget(self)
        stack.addWidget(foreground)

        # StackAll keeps every widget visible, but only the "current" widget
        # is raised to the top of the z-order. addWidget() left currentIndex
        # at 0 (background), so the opaque HUD paint was covering the chat
        # UI completely. This raises the foreground above it.
        stack.setCurrentWidget(foreground)

        layout = QVBoxLayout(foreground)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)

        # Title row: name + a small status dot that shifts color while busy.
        title_row = QHBoxLayout()
        title_row.setSpacing(8)

        title = QLabel("LYRA")
        title.setObjectName("title")
        title_glow = QGraphicsDropShadowEffect(title)
        title_glow.setColor(QColor(ACCENT.red(), ACCENT.green(), ACCENT.blue(), 160))
        title_glow.setBlurRadius(24)
        title_glow.setOffset(0, 0)
        title.setGraphicsEffect(title_glow)
        title_row.addWidget(title)

        self.status_dot = QLabel("\u25cf")
        self.status_dot.setObjectName("statusDot")
        title_row.addWidget(self.status_dot)

        title_row.addStretch(1)

        self.status_label = QLabel("")
        self.status_label.setObjectName("status")
        title_row.addWidget(self.status_label)

        layout.addLayout(title_row)

        # Transcript: a scrollable stack of MessageBubble rows instead of a
        # single QTextEdit -- gives each message real rounded corners, a
        # per-role accent color/glow, and left/right alignment.
        self.transcript_scroll = QScrollArea()
        self.transcript_scroll.setObjectName("transcriptScroll")
        self.transcript_scroll.setWidgetResizable(True)
        self.transcript_scroll.setFrameShape(QFrame.NoFrame)
        self.transcript_scroll.viewport().setStyleSheet("background: transparent;")

        transcript_container = QWidget()
        transcript_container.setStyleSheet("background: transparent;")
        self.transcript_layout = QVBoxLayout(transcript_container)
        self.transcript_layout.setContentsMargins(10, 10, 10, 10)
        self.transcript_layout.setSpacing(10)
        self.transcript_layout.addStretch(1)  # keeps bubbles pinned to the bottom

        self.transcript_scroll.setWidget(transcript_container)
        layout.addWidget(self.transcript_scroll, stretch=1)

        # Auto-scroll driven by the scrollbar's own range-changed signal,
        # not a guessed delay -- this fires exactly when the transcript's
        # content height actually changes (e.g. once a wrapped multi-line
        # reply has finished laying out), so it can't undershoot.
        self.transcript_scroll.verticalScrollBar().rangeChanged.connect(
            lambda _min, mx: self.transcript_scroll.verticalScrollBar().setValue(mx)
        )

        input_row = QHBoxLayout()

        # Text input is the permanent fallback (Phase 3 adds voice on top of
        # this, never replacing it — see plan's "Rules Throughout").
        self.input_box = QLineEdit()
        self.input_box.setPlaceholderText("Type a message and press Enter...")
        self.input_box.returnPressed.connect(self.send_message)
        input_row.addWidget(self.input_box, stretch=1)

        self.send_button = QPushButton("Send")
        self.send_button.clicked.connect(self.send_message)
        send_glow = QGraphicsDropShadowEffect(self.send_button)
        send_glow.setColor(QColor(ACCENT.red(), ACCENT.green(), ACCENT.blue(), 130))
        send_glow.setBlurRadius(16)
        send_glow.setOffset(0, 0)
        self.send_button.setGraphicsEffect(send_glow)
        input_row.addWidget(self.send_button)

        layout.addLayout(input_row)

        self._set_busy(False)  # sets the initial status-dot color
        self.input_box.setFocus()

    def send_message(self):
        prompt = self.input_box.text().strip()
        if not prompt:
            return

        self._append_line("You", prompt)
        self.input_box.clear()
        self._set_busy(True)
        self._current_reply_bubble = None  # next chunk_ready starts a fresh reply bubble
        self._pending_chunk_text = ""

        self._worker = LLMWorker(prompt)
        self._worker.chunk_ready.connect(self._on_chunk)
        self._worker.error_occurred.connect(self._on_error)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.start()

    def _on_chunk(self, chunk: str):
        # Just buffer here -- _flush_pending_chunk (on the timer) is what
        # actually touches the bubble/layout, so bursts of chunks collapse
        # into one UI update per tick instead of one per chunk.
        self._pending_chunk_text += chunk
        if not self._flush_timer.isActive():
            self._flush_timer.start()

    def _flush_pending_chunk(self):
        if not self._pending_chunk_text:
            return
        text, self._pending_chunk_text = self._pending_chunk_text, ""
        if self._current_reply_bubble is None:
            # First flush of this reply: start a new bubble seeded with it.
            self._current_reply_bubble = self._append_line("Lyra", text)
        else:
            # Later flushes: grow the same bubble instead of adding new rows.
            self._current_reply_bubble.append_text(text)

    def _on_error(self, message: str):
        self._append_line("Error", message, is_error=True)

    def _on_worker_finished(self):
        self._flush_timer.stop()
        self._flush_pending_chunk()  # don't drop whatever hasn't been flushed yet
        self._current_reply_bubble = None  # this reply is done; next one starts fresh
        self._set_busy(False)
        self.input_box.setFocus()

    def _set_busy(self, busy: bool):
        self.input_box.setEnabled(not busy)
        self.send_button.setEnabled(not busy)
        self.status_label.setText("Thinking..." if busy else "")
        dot_color = "#fbbf24" if busy else ACCENT.name()  # amber while thinking, cyan when idle
        self.status_dot.setStyleSheet(f"color: {dot_color};")

    def _append_line(self, speaker: str, text: str, is_error: bool = False):
        role = "error" if is_error else ("you" if speaker == "You" else "assistant")
        row, bubble = make_row(speaker, text, role)
        # Insert before the trailing stretch so new bubbles land at the bottom.
        # No manual scroll call needed here -- the rangeChanged connection
        # made in _build_ui handles it once the new bubble's real height
        # (after word-wrap layout) is known.
        self.transcript_layout.insertLayout(self.transcript_layout.count() - 1, row)
        return bubble


TRANSITION_MS = 550  # splash -> chat handoff duration, in ms


def _centered_geometry(width: int, height: int) -> QRect:
    # A width x height rect centered on the primary screen.
    screen = QApplication.primaryScreen()
    avail = screen.availableGeometry() if screen else QRect(0, 0, width, height)
    x = avail.x() + (avail.width() - width) // 2
    y = avail.y() + (avail.height() - height) // 2
    return QRect(x, y, width, height)


def _transition_to_chat(splash, window):
    # Cross-fade handoff instead of an instant cut: the chat window grows
    # out of the splash's footprint and fades in, while the splash fades
    # out underneath it, at the same time.
    final_rect = _centered_geometry(window.width(), window.height())
    start_rect = splash.geometry()

    window.setWindowOpacity(0.0)
    window.setGeometry(start_rect)
    window.show()

    geo_anim = QPropertyAnimation(window, b'geometry')
    geo_anim.setDuration(TRANSITION_MS)
    geo_anim.setStartValue(start_rect)
    geo_anim.setEndValue(final_rect)
    geo_anim.setEasingCurve(QEasingCurve.OutCubic)

    fade_anim = QPropertyAnimation(window, b'windowOpacity')
    fade_anim.setDuration(TRANSITION_MS)
    fade_anim.setStartValue(0.0)
    fade_anim.setEndValue(1.0)
    fade_anim.setEasingCurve(QEasingCurve.OutCubic)

    group = QParallelAnimationGroup()
    group.addAnimation(geo_anim)
    group.addAnimation(fade_anim)
    group.finished.connect(window.input_box.setFocus)
    group.start()

    # Qt animations stop dead if their Python object gets garbage-collected
    # mid-flight -- parking the group on window keeps it alive for the run.
    window._transition_anim = group

    splash.fade_out(TRANSITION_MS, splash.close)


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(QSS)

    splash = SplashScreen()
    window = ChatWindow()

    splash.play(lambda: _transition_to_chat(splash, window))

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
