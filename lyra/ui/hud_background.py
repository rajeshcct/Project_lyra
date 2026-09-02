"""
Static HUD-style background.

Pure QPainter — a faint accent-colored dot grid over a near-black
background, rendered once into a cached pixmap and just blitted after
that. This used to also sweep an animated scanline via a ~30fps QTimer
that repainted the entire window continuously, even at total idle — that
constant background CPU draw is what "GUI load" was pointing at, so the
timer and the scanline are both gone. What's left keeps the same HUD look
without anything ticking in the background.

This is an original composition inspired by sci-fi HUD aesthetics generally
— it deliberately does not reproduce any specific film/franchise's branded
interface elements (logos, character names, etc.), since those are someone
else's IP even in a personal project.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QPen, QColor, QPixmap
from PySide6.QtWidgets import QWidget

from .theme import ACCENT, BG_DARK

GRID_STEP = 28


class HudBackground(QWidget):
    """Drop this behind your real UI in a QStackedLayout(StackAll)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._grid_cache = None  # static, so it's rendered once and reused rather than redrawn every frame

    def resizeEvent(self, event):
        self._grid_cache = None  # size changed, cached grid pixmap no longer matches
        super().resizeEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), BG_DARK)
        self._draw_grid(painter)

    def _draw_grid(self, painter: QPainter):
        if self._grid_cache is None:
            pixmap = QPixmap(self.size())
            pixmap.fill(Qt.transparent)
            c = ACCENT
            gp = QPainter(pixmap)
            pen = QPen(QColor(c.red(), c.green(), c.blue(), 16))
            pen.setWidth(1)
            gp.setPen(pen)
            for x in range(0, self.width(), GRID_STEP):
                for y in range(0, self.height(), GRID_STEP):
                    gp.drawPoint(x, y)
            gp.end()
            self._grid_cache = pixmap
        painter.drawPixmap(0, 0, self._grid_cache)
