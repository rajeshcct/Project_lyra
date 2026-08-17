"""
Central visual theme for Lyra's UI.

One accent color, one place to tweak it. main.py, splash.py, and
hud_background.py all pull their look from here instead of hardcoding hex
values inline — change the whole app's color scheme by editing this file
only.
"""

from PySide6.QtGui import QColor

ACCENT = QColor("#22d3ee")        # cyan-blue — primary glow / highlight color
ACCENT_DIM = QColor("#0e7490")    # darker cyan — borders, secondary accents
BG_DARK = QColor("#0a0e14")       # near-black panel background
BG_PANEL = QColor("#10161f")      # slightly lighter panel background
TEXT_MAIN = QColor("#e8f6fb")     # primary readable text
TEXT_DIM = QColor("#7fa8b8")      # secondary/status text
ERROR = QColor("#ff6b6b")         # error messages

QSS = f"""
QWidget {{
    background: transparent;
    color: {TEXT_MAIN.name()};
    font-family: 'Consolas', 'Cascadia Mono', monospace;
}}

QLabel#title {{
    font-size: 24px;
    font-weight: 700;
    color: {ACCENT.name()};
    letter-spacing: 5px;
    padding: 6px 0;
}}

QLabel#statusDot {{
    font-size: 14px;
    padding: 0 4px;
}}

QScrollArea#transcriptScroll {{
    background: rgba(16, 22, 31, 200);
    border: 1px solid {ACCENT_DIM.name()};
    border-radius: 10px;
}}
QScrollArea#transcriptScroll > QWidget > QWidget {{
    background: transparent;
}}

QTextEdit {{
    background: rgba(16, 22, 31, 200);
    border: 1px solid {ACCENT_DIM.name()};
    border-radius: 8px;
    padding: 10px;
    color: {TEXT_MAIN.name()};
    selection-background-color: {ACCENT.name()};
    font-size: 13px;
}}

QLineEdit {{
    background: rgba(16, 22, 31, 220);
    border: 1px solid {ACCENT_DIM.name()};
    border-radius: 8px;
    padding: 10px 14px;
    color: {TEXT_MAIN.name()};
    font-size: 13px;
}}
QLineEdit:focus {{
    border: 1px solid {ACCENT.name()};
}}

QPushButton {{
    background: rgba(34, 211, 238, 30);
    border: 1px solid {ACCENT.name()};
    border-radius: 8px;
    padding: 10px 22px;
    color: {ACCENT.name()};
    font-weight: 700;
}}
QPushButton:hover {{
    background: rgba(34, 211, 238, 70);
}}
QPushButton:pressed {{
    background: rgba(34, 211, 238, 110);
}}
QPushButton:disabled {{
    border-color: {ACCENT_DIM.name()};
    color: {ACCENT_DIM.name()};
    background: transparent;
}}

QLabel#status {{
    color: {TEXT_DIM.name()};
    font-style: italic;
}}

QScrollBar:vertical {{
    background: transparent;
    width: 10px;
}}
QScrollBar::handle:vertical {{
    background: {ACCENT_DIM.name()};
    border-radius: 5px;
    min-height: 24px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
"""
