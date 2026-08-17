"""
Chat message bubbles.

One self-contained QFrame per message, dropped into a QVBoxLayout inside a
QScrollArea (see main.py's ChatWindow). This replaces appending HTML lines
to a single QTextEdit: real rounded corners, a per-role accent color, a
soft glow, and left/right alignment aren't things Qt's rich-text engine
(QTextEdit's HTML subset) supports, but a styled QFrame gets all of them
via normal QSS.

Same "one visual concern per file" pattern as theme.py / hud_background.py.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QVBoxLayout,
    QLabel,
)

from theme import ACCENT, TEXT_MAIN, ERROR

MAX_BUBBLE_WIDTH = 1000
MIN_BUBBLE_WIDTH = 90
BUBBLE_H_PADDING = 12 + 12 + 6  # inner.setContentsMargins L+R plus a little breathing room

_ROLE_STYLES = {
    "you": {
        "accent": QColor("#7dd3fc"),
        "bg": "rgba(125, 211, 252, 24)",
        "align": Qt.AlignRight,
    },
    "assistant": {
        "accent": ACCENT,
        "bg": "rgba(34, 211, 238, 18)",
        "align": Qt.AlignLeft,
    },
    "error": {
        "accent": ERROR,
        "bg": "rgba(255, 107, 107, 22)",
        "align": Qt.AlignLeft,
    },
}


class MessageBubble(QFrame):
    """One message: a small header label + wrapped body text, role-colored."""

    def __init__(self, speaker: str, text: str, role: str, parent=None):
        super().__init__(parent)
        style = _ROLE_STYLES.get(role, _ROLE_STYLES["assistant"])
        accent = style["accent"]

        self.setObjectName("bubble")
        self.setStyleSheet(
            f"""
            QFrame#bubble {{
                background: {style["bg"]};
                border: 1px solid {accent.name()};
                border-radius: 10px;
            }}
            """
        )

        inner = QVBoxLayout(self)
        inner.setContentsMargins(12, 8, 12, 8)
        inner.setSpacing(3)

        header = QLabel(speaker.upper())
        header.setStyleSheet(
            f"color: {accent.name()}; font-weight: 700; font-size: 10px; "
            "letter-spacing: 1px; background: transparent; border: none;"
        )
        inner.addWidget(header)

        body = QLabel(text)
        body.setWordWrap(True)
        body.setTextFormat(Qt.PlainText)  # message text is never HTML
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        body.setStyleSheet(
            f"color: {TEXT_MAIN.name()}; font-size: 13px; "
            "background: transparent; border: none;"
        )
        inner.addWidget(body)
        self._body = body  # kept so append_text() can grow this bubble for streaming replies

        # QLabel.sizeHint(), for a word-wrapped label, is the width needed
        # to fit the text on ONE line -- exactly the "natural" width we want.
        # Without this, the frame only had a max-width, so every bubble just
        # stretched to whatever the layout handed it instead of hugging its
        # own text, which is why short and long messages looked inconsistent.
        self._resize_to_content()

    def _resize_to_content(self):
        natural_width = self._body.sizeHint().width() + BUBBLE_H_PADDING
        self.setFixedWidth(max(MIN_BUBBLE_WIDTH, min(natural_width, MAX_BUBBLE_WIDTH)))

    def append_text(self, more_text: str):
        """Grow this bubble with another streamed chunk of text."""
        self._body.setText(self._body.text() + more_text)
        self._resize_to_content()


def make_row(speaker: str, text: str, role: str):
    """A MessageBubble wrapped in a row that pins it left or right.

    Returns (row, bubble) -- callers that only need to display a row can
    ignore the second value; streaming replies use it to call
    bubble.append_text() as more chunks arrive.
    """
    bubble = MessageBubble(speaker, text, role)
    style = _ROLE_STYLES.get(role, _ROLE_STYLES["assistant"])

    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    if style["align"] == Qt.AlignRight:
        row.addStretch(1)
        row.addWidget(bubble)
    else:
        row.addWidget(bubble)
        row.addStretch(1)
    return row, bubble
