"""
Phase 4 — reasoning-trace panel.

Shows tool calls and their results live, as they happen, instead of
leaving the user staring at a "Thinking..." status while a tool-enabled
request is in flight. Driven entirely by ToolWorker.tool_event (see
worker.py) via add_event(); main.py calls clear() at the start of every
turn and this panel hides itself again once there's nothing left to show.

Same "small role-tagged label" visual language as chat_bubble.py, just
denser and monospace-leaning since this reads more like a log than a
conversation.
"""

import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QVBoxLayout, QLabel

from .theme import ACCENT, ACCENT_DIM, TEXT_DIM, ERROR


class ReasoningTracePanel(QFrame):
    """Growing log of tool_call / tool_result / tool_error / tool_blocked events."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("tracePanel")
        self.setStyleSheet(
            f"""
            QFrame#tracePanel {{
                background: rgba(34, 211, 238, 12);
                border: 1px solid {ACCENT_DIM.name()};
                border-radius: 8px;
            }}
            """
        )

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(10, 6, 10, 6)
        self._layout.setSpacing(2)

        header = QLabel("REASONING TRACE")
        header.setStyleSheet(
            f"color: {ACCENT.name()}; font-weight: 700; font-size: 10px; "
            "letter-spacing: 1px; background: transparent; border: none;"
        )
        self._layout.addWidget(header)

        # Nothing worth showing until a turn actually calls a tool — most
        # turns won't (calculator only fires when the user asks for math),
        # so keeping this hidden by default avoids an empty box sitting in
        # the layout on every ordinary reply.
        self.hide()

    def clear(self):
        """Drop every event line from the previous turn; keep the header."""
        while self._layout.count() > 1:
            item = self._layout.takeAt(1)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.hide()

    def add_event(self, event: dict):
        line = QLabel(self._format(event))
        line.setWordWrap(True)
        line.setTextFormat(Qt.PlainText)
        line.setTextInteractionFlags(Qt.TextSelectableByMouse)
        color = ERROR if event.get("type") in ("tool_error", "tool_blocked") else TEXT_DIM
        line.setStyleSheet(
            f"color: {color.name()}; font-size: 11px; background: transparent; border: none;"
        )
        self._layout.addWidget(line)
        self.show()  # first event of the turn: reveal the panel

    @staticmethod
    def _format(event: dict) -> str:
        etype = event.get("type")
        name = event.get("name", "?")
        if etype == "tool_call":
            args = json.dumps(event.get("args", {}), ensure_ascii=False)
            return f"\U0001f527 calling {name}({args})"
        if etype == "tool_result":
            return f"    \u2192 {event.get('result', '')}"
        if etype == "tool_error":
            return f"    \u2717 {name} failed: {event.get('error', '')}"
        if etype == "tool_blocked":
            return f"    \u26d4 {name} needs confirmation \u2014 not run"
        return f"    {event}"
