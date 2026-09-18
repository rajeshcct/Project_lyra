"""
Phase 11 — dashboard panel: read-only view over data earlier phases
already collect. Per the plan: "no new backend logic — purely a UI layer
over data you already have." Every data call this panel makes already
existed before this phase:

    Reminders / To-Do  -- reminders.list_reminders() (Phase 5). This
                           project never split "tasks" into their own
                           table separate from reminders -- the plan's
                           own Phase 5 row already treats "Reminders/To-do
                           (SQLite CRUD)" as one thing, so one section
                           covers both.
    Recent Commands     -- memory.get_recent_commands() (Phase 11 addition
                           to memory.py, but it's a plain read-only SELECT
                           over the chat_history table Phase 3 already
                           created -- not new backend logic, just a new
                           query over existing data, kept separate from
                           get_recent_turns() so it never touches what's
                           sent to the model).
    Indexed Documents    -- rag.list_documents() (Phase 9), whose own
                           docstring already said "for a future dashboard
                           panel (Phase 11)".

Refresh strategy: a QTimer polls all three sources every REFRESH_MS while
the panel is visible -- satisfies the plan's Phase 11 checkpoint
("dashboard accurately reflects live state ... without needing a manual
refresh") without wiring change-notification callbacks through three
modules that were never built to emit them. The timer starts on showEvent
and stops on hideEvent, so a hidden/collapsed dashboard costs nothing.

Person A/B split per the plan: layout/styling below follows trace_panel.py's
"titled box of small labels" visual language; the refresh/correctness half
(what to query, when, and how to render an empty state) is the other half
of that same split.
"""

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QFrame, QScrollArea

from .. import reminders, memory, rag
from .theme import ACCENT, ACCENT_DIM, TEXT_DIM, TEXT_MAIN

REFRESH_MS = 4000  # local SQLite/Chroma reads are cheap at this data volume


class _Section(QFrame):
    """One titled, scrollable list — Reminders / Recent Commands / Documents
    all share this exact shape, just with different data and empty-state text."""

    def __init__(self, title: str, empty_text: str, parent=None):
        super().__init__(parent)
        self._empty_text = empty_text
        self.setStyleSheet(
            f"""
            QFrame {{
                background: rgba(34, 211, 238, 10);
                border: 1px solid {ACCENT_DIM.name()};
                border-radius: 8px;
            }}
            """
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 8)
        outer.setSpacing(4)

        header = QLabel(title.upper())
        header.setStyleSheet(
            f"color: {ACCENT.name()}; font-weight: 700; font-size: 10px; "
            "letter-spacing: 1px; background: transparent; border: none;"
        )
        outer.addWidget(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.viewport().setStyleSheet("background: transparent;")
        scroll.setFixedHeight(90)

        self._list_container = QWidget()
        self._list_container.setStyleSheet("background: transparent;")
        self._list_layout = QVBoxLayout(self._list_container)
        self._list_layout.setContentsMargins(2, 2, 2, 2)
        self._list_layout.setSpacing(2)
        self._list_layout.addStretch(1)

        scroll.setWidget(self._list_container)
        outer.addWidget(scroll)

    def set_items(self, lines: list[str]):
        """Replace the list's contents. Same trick as
        ReasoningTracePanel.clear(): keep the trailing stretch item, drop
        everything above it before rebuilding."""
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        display = lines if lines else [self._empty_text]
        color = TEXT_MAIN if lines else TEXT_DIM
        for line in display:
            label = QLabel(line)
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            label.setStyleSheet(
                f"color: {color.name()}; font-size: 12px; background: transparent; border: none;"
            )
            self._list_layout.insertWidget(self._list_layout.count() - 1, label)


class DashboardPanel(QWidget):
    """Phase 11 -- three read-only panels over existing data, live-refreshed
    while visible. Hidden by default (toggled by main.py's dashboard
    button), same "costs nothing until asked for" spirit as
    ReasoningTracePanel starting hidden."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._reminders_section = _Section("Reminders / To-Do", "No outstanding reminders.")
        self._commands_section = _Section("Recent Commands", "No commands yet.")
        self._documents_section = _Section("Indexed Documents", "No documents uploaded yet.")

        layout.addWidget(self._reminders_section)
        layout.addWidget(self._commands_section)
        layout.addWidget(self._documents_section)

        self._timer = QTimer(self)
        self._timer.setInterval(REFRESH_MS)
        self._timer.timeout.connect(self.refresh)

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()  # don't wait REFRESH_MS for the first paint
        self._timer.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._timer.stop()

    def refresh(self):
        self._refresh_reminders()
        self._refresh_commands()
        self._refresh_documents()

    def _refresh_reminders(self):
        try:
            items = reminders.list_reminders(include_done=False)
        except Exception:
            items = []
        lines = []
        for item in items:
            when = f" — {item['remind_at']}" if item.get("remind_at") else ""
            lines.append(f"#{item['id']}: {item['text']}{when}")
        self._reminders_section.set_items(lines)

    def _refresh_commands(self):
        try:
            items = memory.get_recent_commands()
        except Exception:
            items = []
        self._commands_section.set_items([item["content"] for item in items])

    def _refresh_documents(self):
        try:
            names = rag.list_documents()
        except Exception:
            # Missing chromadb/sentence-transformers, or store not yet
            # created -- same "don't crash the app over one missing
            # dependency" reasoning every tool in this project already
            # follows. Just show the empty state instead.
            names = []
        self._documents_section.set_items(names)
