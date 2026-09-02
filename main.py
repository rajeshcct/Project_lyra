"""
Phase 2/3/4 — Chat UI + Voice + Tools

Entry point for the GUI. Wires a bare PySide6 window to Phase 1's
llm_client.ask_llm function via a background QThread (worker.py), so the
window never freezes while waiting on the API. Which provider actually
answers (Groq, Gemini, ...) is whatever LLM_PROVIDER is set to in .env —
this file doesn't know or care.

Phase 3 adds voice on top of the same text path, never replacing it:
    mic_worker.py  - QThread wrapper around stt.listen_once()
    tts_worker.py  - QThread wrapper around tts.speak()
Clicking the mic button captures one utterance, drops the recognized text
into the same input box, and calls send_message() exactly as Enter/Send
would. A reply is spoken aloud only if the turn that produced it started
from the mic — typing a message never triggers unsolicited speech. Typed
text remains the permanent fallback the whole way through.

Phase 4 adds tool-calling on top of the same send_message() path: every
turn now goes through worker.py's ToolWorker (lyra/llm_client.py's
ask_llm_with_tools), which gives the model every tool registered in
lyra/tools/ via its native function-calling mechanism. Tool calls/results
stream live into the reasoning-trace panel (lyra/ui/trace_panel.py) while
a turn is in flight, then the final answer appears as a normal bubble.

Visuals live in their own modules, same "swap without touching other
files" principle as providers/:
    theme.py           - color palette + stylesheet (QSS)
    splash.py           - startup splash screen (assets/splash.png, fade-in)
    hud_background.py    - static HUD background painted behind the chat UI
                            (grid pattern only — no per-frame animation, kept light on CPU)

Run:
    python main.py

Checkpoint this satisfies: typed text -> LLM reply appears in the window,
UI never freezes; mic button -> spoken reply, using the same path; asking
for a calculation -> the reasoning-trace panel shows the calculator being
called and its result before the final answer appears.
"""

import sys

from PySide6.QtCore import (
    QRect,
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

from lyra.config import PROVIDER
from lyra.worker import ToolWorker
from lyra.mic_worker import MicWorker
from lyra.tts_worker import TTSWorker
from lyra.ui.theme import QSS, ACCENT
from lyra.ui.splash import SplashScreen
from lyra.ui.hud_background import HudBackground
from lyra.ui.chat_bubble import make_row
from lyra.ui.trace_panel import ReasoningTracePanel


class ChatWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Lyra — Phase 4 Chat ({PROVIDER})")
        self.resize(720, 620)

        self._worker = None  # keep a reference so QThread isn't garbage collected mid-run

        # Phase 3 -- voice. Mic input feeds the same send_message() path as
        # typed text; text stays the permanent fallback (mic is additive,
        # never a replacement). A reply only gets spoken aloud if the turn
        # that produced it was voice-triggered -- typing a message never
        # triggers unsolicited speech.
        self._mic_worker = None
        self._tts_worker = None
        self._voice_turn = False
        self._reply_text_full = ""  # last reply's full text, for TTS once it finishes

        self._build_ui()

    def _build_ui(self):
        # Layer 0: static HUD background (hud_background.py).
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

        # Phase 4 -- reasoning-trace panel: shows tool calls/results live
        # while a tool-enabled request is in flight. Hidden until the first
        # tool event of a turn (see ReasoningTracePanel), so it costs no
        # visual space on ordinary replies that never call a tool.
        self.trace_panel = ReasoningTracePanel()
        layout.addWidget(self.trace_panel)

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

        # Phase 3 -- mic button. Sits next to Send; text input above it stays
        # the permanent fallback per the plan.
        self.mic_button = QPushButton("🎤")
        self.mic_button.setToolTip("Speak a message")
        self.mic_button.setFixedWidth(44)
        self.mic_button.clicked.connect(self.start_listening)
        mic_glow = QGraphicsDropShadowEffect(self.mic_button)
        mic_glow.setColor(QColor(ACCENT.red(), ACCENT.green(), ACCENT.blue(), 130))
        mic_glow.setBlurRadius(16)
        mic_glow.setOffset(0, 0)
        self.mic_button.setGraphicsEffect(mic_glow)
        input_row.addWidget(self.mic_button)

        layout.addLayout(input_row)

        self._set_busy(False)  # sets the initial status-dot color
        self.input_box.setFocus()

    def send_message(self, voice_triggered: bool = False):
        prompt = self.input_box.text().strip()
        if not prompt:
            return

        self._voice_turn = voice_triggered  # only speak the reply if this turn started by voice
        self._append_line("You", prompt)
        self.input_box.clear()
        self._set_busy(True)
        self._reply_text_full = ""
        self.trace_panel.clear()  # drop the previous turn's tool trace, if any

        # Phase 4: every turn goes through the tool-enabled path. Tool
        # calling can't be streamed the way a plain reply can (the model
        # has to finish deciding whether to call a tool before any final
        # answer text exists at all -- see ToolWorker's docstring), so the
        # reply arrives whole via reply_ready instead of piece-by-piece via
        # chunk_ready; the trace panel is what keeps the wait from feeling
        # like dead air on turns that actually use a tool.
        self._worker = ToolWorker(prompt)
        self._worker.tool_event.connect(self.trace_panel.add_event)
        self._worker.reply_ready.connect(self._on_reply_ready)
        self._worker.error_occurred.connect(self._on_error)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.start()

    def start_listening(self):
        """Mic button handler: capture one utterance, then send it as if typed."""
        if self._mic_worker is not None:
            return  # already listening -- ignore a repeat click

        self._set_busy(True)
        self.status_label.setText("Listening...")  # override _set_busy's default "Thinking..."

        self._mic_worker = MicWorker()
        self._mic_worker.text_ready.connect(self._on_mic_text)
        self._mic_worker.error_occurred.connect(self._on_mic_error)
        self._mic_worker.finished.connect(self._on_mic_finished)
        self._mic_worker.start()

    def _on_mic_text(self, text: str):
        self.input_box.setText(text)
        self.send_message(voice_triggered=True)

    def _on_mic_error(self, message: str):
        self._append_line("Error", message, is_error=True)

    def _on_mic_finished(self):
        # If recognition succeeded, send_message() already re-armed busy
        # state for the LLM call that's now running -- only clear busy here
        # if that never happened (recognition failed or produced nothing).
        self._mic_worker = None
        if self._worker is None or not self._worker.isRunning():
            self._set_busy(False)

    def _on_reply_ready(self, text: str):
        # Phase 4's tool-enabled replies arrive whole (see ToolWorker) --
        # no streaming bubble to grow, just append the finished answer.
        self._reply_text_full = text
        self._append_line("Lyra", text)

    def _on_error(self, message: str):
        self._append_line("Error", message, is_error=True)

    def _on_worker_finished(self):
        if self._voice_turn and self._reply_text_full.strip():
            self._speak_reply(self._reply_text_full)
        else:
            self._set_busy(False)
            self.input_box.setFocus()
        self._voice_turn = False

    def _speak_reply(self, text: str):
        self.status_label.setText("Speaking...")
        self._tts_worker = TTSWorker(text)
        self._tts_worker.error_occurred.connect(self._on_tts_error)
        self._tts_worker.finished.connect(self._on_tts_finished)
        self._tts_worker.start()

    def _on_tts_error(self, message: str):
        self._append_line("Error", message, is_error=True)

    def _on_tts_finished(self):
        self._tts_worker = None
        self._set_busy(False)
        self.input_box.setFocus()

    def _set_busy(self, busy: bool):
        self.input_box.setEnabled(not busy)
        self.send_button.setEnabled(not busy)
        self.mic_button.setEnabled(not busy)
        # _speak_reply() overrides this to "Speaking..." right after busy is
        # set True for a voice turn's reply -- that happens after this call
        # returns, so it isn't clobbered here.
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
