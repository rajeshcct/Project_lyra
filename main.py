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
a turn is in flight, and the final answer itself streams in token-by-token
into its own bubble via ToolWorker.chunk_ready, exactly like the plain
non-tool path -- only the tool-decision step has no text to stream.

Phase 11 adds a read-only dashboard on top of everything above: a toggle
button (\U0001F4CA) shows/hides lyra/ui/dashboard_panel.py, which polls
reminders.py's SQLite table, memory.py's chat_history, and rag.py's
Chroma store on a timer -- no new backend logic, purely a UI layer over
data every earlier phase already collects.

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

# --- Environment compatibility shim -- must run before ANY other import ---
# `six` (a dependency of dateparser, and possibly vendored by other SDKs
# this app uses) installs a meta path finder (_SixMetaPathImporter) into
# sys.meta_path so `six.moves.*` submodules import correctly. On this
# environment (Python 3.12 + this six version), something later in the
# import chain ends up doing getattr(<that importer instance>, "_path"),
# which raises AttributeError because that attribute is never set on the
# instance -- crashing app startup with:
#     AttributeError: '_SixMetaPathImporter' object has no attribute '_path'
# This is a known six / Python-3.12 importlib incompatibility, not
# anything wrong in this project's own code. Rather than requiring an
# environment fix (upgrading/reinstalling `six`), this patches a
# class-level fallback for `_path` the moment `six` is first imported
# ANYWHERE in the process -- so later `getattr(importer, "_path")` calls
# fall back to this instead of raising, no matter which import first
# triggers them. Must run before lyra.* imports below, since those are
# what eventually pull in dateparser (-> six) via tools/reminder_tool.py.
# Wrapped in try/except so it's a silent no-op wherever `six` isn't
# installed or the bug doesn't apply.
try:
    import six as _six
    if not hasattr(_six._SixMetaPathImporter, "_path"):
        _six._SixMetaPathImporter._path = None
except Exception:
    pass

import re
import sys
from collections import deque

from PySide6.QtCore import (
    QRect,
    QTimer,
    QPropertyAnimation,
    QParallelAnimationGroup,
    QEasingCurve,
    Signal,
)
from PySide6.QtGui import QColor, QIcon
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
    QMessageBox,
    QSystemTrayIcon,
    QFileDialog,
)

from pathlib import Path

from lyra.config import PROVIDER
from lyra.worker import ToolWorker, NewSessionWorker
from lyra.mic_worker import MicWorker
from lyra.tts_worker import TTSWorker
from lyra.scheduler import ReminderScheduler
from lyra.rag_worker import RagIngestWorker
from lyra.ui.theme import QSS, ACCENT
from lyra.ui.splash import SplashScreen
from lyra.ui.hud_background import HudBackground
from lyra.ui.chat_bubble import make_row
from lyra.ui.trace_panel import ReasoningTracePanel
from lyra.ui.dashboard_panel import DashboardPanel
from lyra.paths import BUNDLE_ROOT

ASSETS_DIR = BUNDLE_ROOT / "assets"


class ChatWindow(QWidget):
    # Phase 14 -- emitted by tools/window_tool.py's show_window() from the
    # ToolWorker background thread. QWidget methods (raise_/activateWindow)
    # aren't safe to call from a non-GUI thread, but emitting a Qt signal
    # is -- Qt auto-queues delivery of the connected slot onto this
    # window's own GUI thread, same cross-thread pattern already used for
    # tool_event/chunk_ready/confirmation_requested below.
    bring_to_foreground = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Lyra — Phase 11 Chat ({PROVIDER})")
        self.resize(720, 700)

        self._worker = None  # keep a reference so QThread isn't garbage collected mid-run

        # Phase 3 -- voice. Mic input feeds the same send_message() path as
        # typed text; text stays the permanent fallback (mic is additive,
        # never a replacement). A reply only gets spoken aloud if the turn
        # that produced it was voice-triggered -- typing a message never
        # triggers unsolicited speech.
        self._mic_worker = None
        self._tts_worker = None
        self._rag_worker = None  # Phase 9 -- keeps a reference so the ingest QThread isn't GC'd mid-run
        self._new_session_worker = None  # Phase 15 -- same GC-reference reasoning as the other *_worker attrs
        self._voice_turn = False
        self._hands_free = False  # True after mic button is toggled on -- keeps re-listening
        self._reply_text_full = ""  # last reply's full text, for TTS once it finishes
        self._reply_bubble = None  # bubble the current turn's streamed reply is being written into

        # Word-by-word reveal: raw provider chunks arrive in irregular,
        # sometimes-multi-word bursts (network-dependent), which is what
        # made streaming feel fast/jumpy. Chunks are buffered here and
        # released one word at a time on a fixed timer instead, so display
        # speed is controlled and readable regardless of how the chunks
        # actually arrive over the wire.
        self._stream_leftover = ""  # partial word at the end of the buffer, not yet a whole word
        self._word_queue = deque()
        self._reveal_timer = QTimer(self)
        self._reveal_timer.setInterval(100)  # ms between words -- raise/lower to slow/speed up
        self._reveal_timer.timeout.connect(self._reveal_next_word)

        self.bring_to_foreground.connect(self._on_bring_to_foreground)

        self._build_ui()
        self._init_tray_icon()
        self._start_reminder_scheduler()
        self._register_with_window_tool()

    # -- Phase 14 -- voice/text command to raise this window -------------

    def _register_with_window_tool(self):
        """Hands this exact window instance to tools/window_tool.py, once,
        right after it's built -- tools/ modules are plain functions with
        no reference to any QWidget (they're imported at app startup,
        before this window exists), so this one-way hook is how
        show_window() later reaches it."""
        from lyra.tools import window_tool
        window_tool.register_window(self)

    def _on_bring_to_foreground(self):
        """Un-minimize, raise above other windows, and ask Windows for
        input focus. SetForegroundWindow is also called directly via
        ctypes as a fallback -- Qt's activateWindow() alone can be
        silently ignored by Windows' foreground-lock rules if this process
        hasn't received recent input (e.g. the user's been talking to
        another app while Lyra sat in hands-free voice mode)."""
        self.showNormal()
        self.raise_()
        self.activateWindow()
        try:
            import ctypes
            ctypes.windll.user32.SetForegroundWindow(int(self.winId()))
        except Exception:
            pass  # best-effort -- the Qt calls above already cover most cases

    # -- Phase 7 -- reminder scheduler + system notifications ------------

    def _init_tray_icon(self):
        """System tray icon used purely for reminder notifications (Qt's
        QSystemTrayIcon.showMessage needs an icon+tray to attach the popup
        to, even though we never show a context menu). Reuses the splash
        image rather than shipping a second asset."""
        icon_path = ASSETS_DIR / "splash.png"
        icon = QIcon(str(icon_path)) if icon_path.exists() else self.style().standardIcon(
            self.style().StandardPixmap.SP_MessageBoxInformation
        )
        self.tray_icon = QSystemTrayIcon(icon, self)
        self.tray_icon.setToolTip("Lyra")
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray_icon.show()

    def _start_reminder_scheduler(self):
        """Wires lyra/scheduler.py's ReminderScheduler into the running app.
        Backend (polling, email sending) already existed -- this is the
        missing GUI-side half: turn its signals into an actual system
        notification / transcript line, and start/stop it with the app."""
        self._reminder_scheduler = ReminderScheduler(self)
        self._reminder_scheduler.reminder_due.connect(self._on_reminder_due)
        self._reminder_scheduler.reminder_email_sent.connect(self._on_reminder_email_sent)
        self._reminder_scheduler.reminder_email_failed.connect(self._on_reminder_email_failed)
        try:
            self._reminder_scheduler.start()
        except RuntimeError as e:
            # Missing APScheduler -- app still runs fine, reminders just
            # won't self-fire until the dependency is installed (see
            # scheduler.py's module docstring).
            self._append_line("System", str(e), is_error=True)

    def _on_reminder_due(self, reminder: dict):
        text = reminder["text"]
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray_icon.showMessage(
                "Lyra reminder", text, QSystemTrayIcon.MessageIcon.Information, 10000
            )
        self._append_line("Lyra", f"\u23f0 Reminder: {text}")

    def _on_reminder_email_sent(self, info: dict):
        self._append_line("System", f"Reminder email sent to {info['email_to']}.")

    def _on_reminder_email_failed(self, info: dict):
        self._append_line(
            "System",
            f"Couldn't send reminder email to {info['email_to']}: {info['error']}",
            is_error=True,
        )

    def closeEvent(self, event):
        # Stop the background poller cleanly so it doesn't keep touching
        # this window's Qt objects after Python starts tearing them down.
        if getattr(self, "_reminder_scheduler", None) is not None:
            self._reminder_scheduler.stop()
        super().closeEvent(event)

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

        # Phase 11 -- dashboard panel: read-only reminders/recent-commands/
        # documents view over data earlier phases already collect. Hidden
        # until the dashboard button below is toggled on, same "costs
        # nothing until asked for" spirit as trace_panel starting hidden.
        self.dashboard_panel = DashboardPanel()
        self.dashboard_panel.hide()
        layout.addWidget(self.dashboard_panel)

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
        self.mic_button.setObjectName("iconButton")
        self.mic_button.setToolTip("Toggle hands-free listening (no need to click each turn)")
        self.mic_button.setFixedWidth(44)
        self.mic_button.setCheckable(True)
        self.mic_button.clicked.connect(self._toggle_hands_free)
        mic_glow = QGraphicsDropShadowEffect(self.mic_button)
        mic_glow.setColor(QColor(ACCENT.red(), ACCENT.green(), ACCENT.blue(), 130))
        mic_glow.setBlurRadius(16)
        mic_glow.setOffset(0, 0)
        self.mic_button.setGraphicsEffect(mic_glow)
        input_row.addWidget(self.mic_button)

        # Phase 9 -- upload button. Feeds lyra/rag.py via RagIngestWorker
        # (background thread, same reasoning as mic/tts) rather than the
        # tool-calling path -- the model has no business picking which file
        # on disk gets indexed, that's a user action through a real file
        # dialog, per the plan's "Person A builds upload UI" split.
        self.upload_button = QPushButton("\U0001F4CE")
        self.upload_button.setObjectName("iconButton")
        self.upload_button.setToolTip("Upload a PDF or text file for Lyra to search")
        self.upload_button.setFixedWidth(44)
        self.upload_button.clicked.connect(self._on_upload_clicked)
        upload_glow = QGraphicsDropShadowEffect(self.upload_button)
        upload_glow.setColor(QColor(ACCENT.red(), ACCENT.green(), ACCENT.blue(), 130))
        upload_glow.setBlurRadius(16)
        upload_glow.setOffset(0, 0)
        self.upload_button.setGraphicsEffect(upload_glow)
        input_row.addWidget(self.upload_button)

        # Phase 11 -- dashboard toggle. Shows/hides the read-only panel
        # built above; DashboardPanel's own showEvent/hideEvent start and
        # stop its refresh timer, so this button doesn't need to manage
        # that itself.
        self.dashboard_button = QPushButton("\U0001F4CA")
        self.dashboard_button.setObjectName("iconButton")
        self.dashboard_button.setToolTip("Show/hide the dashboard (reminders, recent commands, documents)")
        self.dashboard_button.setFixedWidth(44)
        self.dashboard_button.setCheckable(True)
        self.dashboard_button.clicked.connect(self._toggle_dashboard)
        dashboard_glow = QGraphicsDropShadowEffect(self.dashboard_button)
        dashboard_glow.setColor(QColor(ACCENT.red(), ACCENT.green(), ACCENT.blue(), 130))
        dashboard_glow.setBlurRadius(16)
        dashboard_glow.setOffset(0, 0)
        self.dashboard_button.setGraphicsEffect(dashboard_glow)
        input_row.addWidget(self.dashboard_button)

        # Phase 15 -- new session button. For when a conversation has gone
        # on very, very long and is at risk of outgrowing the provider's
        # context window: folds whatever's left of the current session
        # into the persistent rolling summary (see memory.start_new_session),
        # then clears the visible transcript for a clean slate. Name,
        # preferences, and the summary itself all survive the switch --
        # only the raw per-session turn history and the on-screen chat
        # reset.
        self.new_session_button = QPushButton("\U0001F195")
        self.new_session_button.setObjectName("iconButton")
        self.new_session_button.setToolTip(
            "Start a new session -- folds this conversation into memory, "
            "then clears the chat. Use this if a conversation has been "
            "going on for a very long time."
        )
        self.new_session_button.setFixedWidth(44)
        self.new_session_button.clicked.connect(self._on_new_session_clicked)
        new_session_glow = QGraphicsDropShadowEffect(self.new_session_button)
        new_session_glow.setColor(QColor(ACCENT.red(), ACCENT.green(), ACCENT.blue(), 130))
        new_session_glow.setBlurRadius(16)
        new_session_glow.setOffset(0, 0)
        self.new_session_button.setGraphicsEffect(new_session_glow)
        input_row.addWidget(self.new_session_button)

        # Stop button: only meaningful while a request is in flight, so it
        # starts hidden and _set_busy() toggles its visibility. Cancels the
        # in-flight ToolWorker cooperatively (see ToolWorker.cancel) rather
        # than killing the thread outright.
        self.stop_button = QPushButton("■ Stop")
        self.stop_button.setToolTip("Cancel the current request")
        self.stop_button.clicked.connect(self._on_stop_clicked)
        self.stop_button.hide()
        input_row.addWidget(self.stop_button)

        layout.addLayout(input_row)

        self._set_busy(False)  # sets the initial status-dot color
        self.input_box.setFocus()

    def send_message(self, voice_triggered: bool = False):
        prompt = self.input_box.text().strip()
        if not prompt:
            return

        # Phase 15 -- the mic button stays enabled even while _set_busy(True)
        # (see its comment below), which means hands-free voice could still
        # turn a recognized utterance into a send_message() call while a
        # new-session switch is running in the background. Letting that
        # through would log this turn against whichever session_id happens
        # to win the race, and could interleave with _clear_transcript()
        # wiping the transcript mid-append -- so this is refused the same
        # way an empty prompt is, rather than proceeding.
        if self._new_session_worker is not None:
            self._append_line(
                "System",
                "Starting a new session -- try that again in a moment.",
            )
            return

        self._voice_turn = voice_triggered  # only speak the reply if this turn started by voice
        self._append_line("You", prompt)
        self.input_box.clear()
        self._set_busy(True)
        self._reply_text_full = ""
        self._reply_bubble = None  # created lazily by _on_chunk_ready once the first chunk lands
        self._stream_leftover = ""
        self._word_queue.clear()
        self._reveal_timer.stop()
        self.trace_panel.clear()  # drop the previous turn's tool trace, if any

        # Phase 4: every turn goes through the tool-enabled path. The
        # tool-decision step itself can't be streamed (the model has to
        # finish deciding whether to call a tool before any answer text
        # exists at all -- see ToolWorker's docstring), so the trace panel
        # is what keeps that part from feeling like dead air. The actual
        # answer text -- direct reply or the follow-up after a tool runs --
        # streams in via chunk_ready and grows the bubble live, same as the
        # plain non-tool path.
        self._worker = ToolWorker(prompt)
        self._worker.tool_event.connect(self.trace_panel.add_event)
        self._worker.chunk_ready.connect(self._on_chunk_ready)
        self._worker.reply_ready.connect(self._on_reply_ready)
        self._worker.error_occurred.connect(self._on_error)
        self._worker.confirmation_requested.connect(self._on_confirmation_requested)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.start()

    def _toggle_hands_free(self, checked: bool):
        """Mic button now toggles a mode rather than firing one listen. When
        turned on, start_listening() re-arms itself automatically after every
        reply (text and, if spoken, TTS) finishes -- so the user never has to
        click the mic again mid-conversation. Turning it off just stops the
        auto-restart; any listen already in flight still finishes normally."""
        self._hands_free = checked
        self.mic_button.setText("🔴" if checked else "🎤")
        # Bug fix -- self._worker is set once on the very first message and
        # never reset back to None afterward (it just stops running once
        # the reply is in), so the old `self._worker is None` check here
        # only ever passed before any message had been sent at all --
        # hands-free could be turned on once, but a later click could never
        # re-arm it. isRunning() is the real "is a request in flight" test,
        # same one _on_mic_finished already uses below.
        worker_busy = self._worker is not None and self._worker.isRunning()
        if checked and self._mic_worker is None and not worker_busy and self._tts_worker is None:
            self.start_listening()

    def start_listening(self):
        """Capture one utterance, then send it as if typed. Called once per
        turn; when hands-free mode is on, it re-arms itself automatically
        (see _on_mic_finished / _on_tts_finished / _on_worker_finished)."""
        if self._mic_worker is not None:
            return  # already listening -- ignore a repeat click

        # Phase 15 -- don't open the mic mid-session-switch; a recognized
        # utterance would just be refused by send_message()'s own guard
        # anyway, but skipping it here avoids a pointless capture (and the
        # brief "Listening..." status flashing over "Starting new
        # session..."). _on_new_session_finished() re-arms hands-free once
        # the switch is done, so nothing is lost, just delayed.
        if self._new_session_worker is not None:
            return

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
        # "Didn't hear anything" is the normal outcome of an open hands-free
        # mic during silence -- don't spam it into the transcript, just keep
        # listening. Genuine errors (no mic hardware, no permission) still
        # get logged so the user isn't stuck in a silent retry loop.
        if self._hands_free and message.startswith("Didn't hear anything"):
            pass
        else:
            self._append_line("Error", message, is_error=True)

    def _on_mic_finished(self):
        # If recognition succeeded, send_message() already re-armed busy
        # state for the LLM call that's now running -- only clear busy here
        # if that never happened (recognition failed or produced nothing).
        self._mic_worker = None
        if self._worker is None or not self._worker.isRunning():
            self._set_busy(False)
            if self._hands_free:
                self.start_listening()

    # -- Phase 9 -- document upload (RAG) ---------------------------------

    def _on_upload_clicked(self):
        if self._rag_worker is not None:
            return  # an ingest is already running -- ignore a repeat click

        path, _ = QFileDialog.getOpenFileName(
            self,
            "Upload a document",
            "",
            "Documents (*.pdf *.txt *.md)",
        )
        if not path:
            return  # dialog cancelled

        self.upload_button.setEnabled(False)
        self.status_label.setText("Indexing document...")
        self._append_line("System", f"Indexing '{Path(path).name}'...")

        self._rag_worker = RagIngestWorker(path)
        self._rag_worker.done_ready.connect(self._on_rag_done)
        self._rag_worker.error_occurred.connect(self._on_rag_error)
        self._rag_worker.finished.connect(self._on_rag_finished)
        self._rag_worker.start()

    def _on_rag_done(self, summary: str):
        self._append_line("System", summary)

    def _on_rag_error(self, message: str):
        self._append_line("System", message, is_error=True)

    def _on_rag_finished(self):
        self._rag_worker = None
        self.upload_button.setEnabled(True)
        self.status_label.setText("")

    # -- Phase 11 -- dashboard ---------------------------------------------

    def _toggle_dashboard(self, checked: bool):
        self.dashboard_panel.setVisible(checked)

    # -- Phase 15 -- new session (long-chat handoff) -----------------------

    def _on_new_session_clicked(self):
        if self._new_session_worker is not None:
            return  # already in progress -- ignore a repeat click

        # Refuse to switch sessions out from under an in-flight request:
        # memory.log_message() reads the module-level SESSION_ID at the
        # moment it's called, so a request that's still writing its
        # user/assistant turns while SESSION_ID changes underneath it
        # would end up with one turn logged to the old session and the
        # other to the new one -- exactly the kind of split-session mess
        # this feature exists to avoid, not cause. Busy from a text/voice
        # reply, a mic capture, TTS playback, or a document upload all
        # count -- any of them can still be mid-write.
        busy = (
            (self._worker is not None and self._worker.isRunning())
            or self._mic_worker is not None
            or self._tts_worker is not None
            or self._rag_worker is not None
        )
        if busy:
            self._append_line(
                "System",
                "Let the current request finish before starting a new session.",
            )
            return

        self.new_session_button.setEnabled(False)
        self._set_busy(True)
        self.stop_button.hide()  # nothing to cancel here -- _set_busy(True) shows it by default
        self.status_label.setText("Starting new session...")

        self._new_session_worker = NewSessionWorker()
        self._new_session_worker.session_ready.connect(self._on_new_session_ready)
        self._new_session_worker.error_occurred.connect(self._on_new_session_error)
        self._new_session_worker.finished.connect(self._on_new_session_finished)
        self._new_session_worker.start()

    def _on_new_session_ready(self, new_session_id: str):
        # Drop any leftover per-turn streaming state before clearing --
        # none of it applies to the fresh session, and leaving the reveal
        # timer/queue armed could otherwise replay stale words into
        # whatever gets appended next (the same class of bug _on_reply_ready
        # now guards against for a single turn).
        self._reveal_timer.stop()
        self._word_queue.clear()
        self._stream_leftover = ""
        self._reply_bubble = None
        self._reply_text_full = ""
        self.trace_panel.clear()

        self._clear_transcript()
        self._append_line(
            "System",
            "New session started. Earlier context has been folded into "
            "memory, so Lyra still remembers your name, preferences, and "
            "the gist of the conversation so far -- the chat below is just "
            "a clean slate.",
        )

    def _on_new_session_error(self, message: str):
        self._append_line("Error", message, is_error=True)

    def _on_new_session_finished(self):
        self._new_session_worker = None
        self.new_session_button.setEnabled(True)
        self._set_busy(False)
        self.input_box.setFocus()
        # Resume hands-free listening if start_listening() skipped its turn
        # while this was running (see its own new-session guard above).
        if self._hands_free and self._mic_worker is None:
            self.start_listening()

    def _clear_transcript(self):
        """Remove every message bubble from the transcript, keeping the
        trailing stretch item that pins new bubbles to the bottom (see
        _build_ui -- addStretch(1) is added once and every row is inserted
        before it, so it always ends up last)."""
        while self.transcript_layout.count() > 1:
            item = self.transcript_layout.takeAt(0)
            child_layout = item.layout()
            if child_layout is not None:
                self._clear_layout(child_layout)

    @staticmethod
    def _clear_layout(layout):
        """Recursively empty a layout, deleting any widgets it holds.
        Qt's layout removal APIs don't delete child widgets on their own --
        without this, cleared bubbles would keep existing (invisible, but
        alive) instead of actually being freed."""
        while layout.count():
            item = layout.takeAt(0)
            child_widget = item.widget()
            child_layout = item.layout()
            if child_widget is not None:
                child_widget.deleteLater()
            elif child_layout is not None:
                ChatWindow._clear_layout(child_layout)

    def _on_chunk_ready(self, chunk: str):
        # Track the true full text immediately (memory/TTS need the real
        # content regardless of display pacing), but only feed the *visible*
        # bubble complete words, released by _reveal_next_word on a timer --
        # see the buffering note in __init__ for why.
        self._reply_text_full += chunk
        self._stream_leftover += chunk
        whole_words = re.findall(r"\S+\s+", self._stream_leftover)
        if whole_words:
            consumed = "".join(whole_words)
            self._stream_leftover = self._stream_leftover[len(consumed):]
            self._word_queue.extend(whole_words)
            if not self._reveal_timer.isActive():
                self._reveal_timer.start()

    def _reveal_next_word(self):
        """Timer tick: pop one buffered word and grow the bubble with it.
        Stops itself once the queue drains -- restarted by the next
        _on_chunk_ready call (or _flush_stream_leftover at turn end)."""
        if not self._word_queue:
            self._reveal_timer.stop()
            return
        word = self._word_queue.popleft()
        if self._reply_bubble is None:
            self._reply_bubble = self._append_line("Lyra", word)
        else:
            self._reply_bubble.append_text(word)

    def _flush_stream_leftover(self):
        """Called once a turn's text is fully in (reply_ready/worker_finished)
        -- queues whatever trailing partial word never got a following space
        to complete the buffer, so the last word of a reply isn't dropped."""
        if self._stream_leftover:
            self._word_queue.append(self._stream_leftover)
            self._stream_leftover = ""
        if self._word_queue and not self._reveal_timer.isActive():
            self._reveal_timer.start()

    def _on_reply_ready(self, text: str):
        # Normally the bubble is already fully built from chunk_ready by
        # the time this fires -- this just gives the authoritative
        # complete text for memory/TTS bookkeeping.
        #
        # BUG THIS FIXES: on a fast/short reply, every chunk_ready chunk
        # can arrive and reply_ready can fire before the word-reveal timer
        # (100ms interval) ever ticks once, so self._reply_bubble is still
        # None here even though self._word_queue already holds every word
        # of the reply. The old code's fallback then created a bubble with
        # the complete text right here, but left the timer running and the
        # queue untouched, so moments later _reveal_next_word kept firing,
        # saw self._reply_bubble was no longer None, and appended each
        # already-shown word onto that same bubble again. The reply ended
        # up doubled (or briefly tripled) inside one bubble -- this is what
        # showed up as the same response appearing two or three times.
        # Groq streams fast enough that short replies hit this race almost
        # every time.
        #
        # Fix: when about to take the fallback path (no reveal tick ever
        # ran), stop the timer and drop the queued words/leftover first --
        # the full text is being shown directly, so there is nothing left
        # for the timer to redraw. When a bubble already exists, behave
        # exactly as before and just flush the trailing partial word so
        # the timer finishes the reveal normally.
        self._reply_text_full = text
        if self._reply_bubble is None:
            self._reveal_timer.stop()
            self._word_queue.clear()
            self._stream_leftover = ""
            if text:
                self._reply_bubble = self._append_line("Lyra", text)
        else:
            self._flush_stream_leftover()

    def _on_error(self, message: str):
        self._append_line("Error", message, is_error=True)

    def _confirmation_prompt(self, tool_name: str, args: dict) -> str:
        """Build the dialog body for a requires_confirmation tool call.
        Phase 8 -- send_email gets a readable To/Subject/Body preview
        instead of the generic key=value dump, since a multi-line body
        squashed into one comma-joined line would be unreadable right when
        readability matters most (this is the human's one chance to catch
        a bad address or a hallucinated draft before anything real sends).
        Every other confirmation-gated tool keeps the generic format."""
        if tool_name == "send_email":
            to = args.get("to", "")
            subject = args.get("subject", "")
            body = args.get("body", "")
            return (
                "Lyra wants to send this email:\n\n"
                f"To: {to}\n"
                f"Subject: {subject}\n\n"
                f"{body}\n\n"
                "Send it?"
            )
        if tool_name == "write_file":
            # Phase 14 -- same reasoning as send_email above: a multi-line
            # note squashed into one comma-joined key=value line would be
            # unreadable right when readability matters most (this is the
            # human's one chance to catch bad content before it's written).
            filename = args.get("filename", "")
            content = args.get("content", "")
            return (
                "Lyra wants to save this file:\n\n"
                f"Filename: {filename}\n\n"
                f"{content}\n\n"
                "Save it?"
            )
        args_preview = ", ".join(f"{k}={v!r}" for k, v in args.items()) or "(no arguments)"
        return f"Lyra wants to run '{tool_name}' with:\n{args_preview}\n\nAllow this?"

    def _on_confirmation_requested(self, tool_name: str, args: dict):
        """Phase 7 -- ToolWorker.confirmation_requested lands here, on the
        GUI thread (Qt auto-queues it), while the worker thread sits blocked
        inside _on_confirmation_required() waiting on its threading.Event.
        QMessageBox.question() below is itself blocking, which is exactly
        right here -- the whole point is that nothing about this tool call
        proceeds until a human has actually looked at it and clicked
        something. Whatever the user picks is handed straight back to the
        worker via provide_confirmation(), which sets that event."""
        prompt_text = self._confirmation_prompt(tool_name, args)
        answer = QMessageBox.question(
            self,
            "Confirm action",
            prompt_text,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,  # default focus on No -- a sensitive action should never be a stray Enter-press
        )
        if self._worker is not None:
            self._worker.provide_confirmation(answer == QMessageBox.Yes)

    def _on_worker_finished(self):
        if self._voice_turn and self._reply_text_full.strip():
            self._speak_reply(self._reply_text_full)
        else:
            self._set_busy(False)
            self.input_box.setFocus()
            if self._hands_free:
                self.start_listening()
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
        if self._hands_free:
            self.start_listening()

    def _on_stop_clicked(self):
        """Cancel the in-flight request. Cooperative (see ToolWorker.cancel):
        the worker thread keeps running until ask_llm_with_tools notices and
        returns, so _on_worker_finished still fires normally afterwards with
        whatever partial text had already streamed in."""
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self.stop_button.setEnabled(False)
            self.status_label.setText("Stopping...")

    def _set_busy(self, busy: bool):
        self.input_box.setEnabled(not busy)
        self.send_button.setEnabled(not busy)
        # Mic button stays enabled even while busy -- in hands-free mode the
        # app is busy almost continuously (listening/thinking/speaking on
        # loop), so disabling it here would make the toggle unclickable and
        # trap the user in hands-free mode with no way to turn it off.
        self.mic_button.setEnabled(True)
        # Disable non-essential buttons while busy so accidental clicks
        # can't open the dashboard, start a new session, or trigger an
        # upload mid-reply.
        self.upload_button.setEnabled(not busy)
        self.dashboard_button.setEnabled(not busy)
        self.new_session_button.setEnabled(not busy)
        self.stop_button.setVisible(busy)
        self.stop_button.setEnabled(busy)  # fresh (re-)enable at the start of every turn
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
