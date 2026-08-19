"""
Animated HUD-style background.

Pure QPainter — a sweeping scanline over a faint dot grid, drawn in code.
No image assets, so it's resolution-independent and instantly re-themeable
via theme.py's ACCENT color. Runs at ~30fps on a QTimer.

This is an original composition inspired by sci-fi HUD aesthetics generally
— it deliberately does not reproduce any specific film/franchise's branded
interface elements (logos, character names, etc.), since those are someone
else's IP even in a personal project.
"""

from PySide6.QtCore import Qt, QTimer, QRectF
from PySide6.QtGui import QPainter, QPen, QColor, QLinearGradient, QPixmap
from PySide6.QtWidgets import QWidget

from .theme import ACCENT, BG_DARK

FPS_MS = 33          # ~30 fps
SCANLINE_SPEED_PX_PER_SEC = 60
GRID_STEP = 28


class HudBackground(QWidget):
    """Drop this behind your real UI in a QStackedLayout(StackAll)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._t = 0.0
        self._grid_cache = None  # static, so it's rendered once and reused rather than redrawn every frame
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(FPS_MS)

    def resizeEvent(self, event):
        self._grid_cache = None  # size changed, cached grid pixmap no longer matches
        super().resizeEvent(event)

    def _tick(self):
        self._t += FPS_MS / 1000.0
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), BG_DARK)

        self._draw_grid(painter)
        self._draw_scanline(painter)

    def _draw_grid(self, painter: QPainter):
        # The dot grid never moves -- only the scanline animates -- so
        # painting it with hundreds of individual drawPoint() calls on
        # every single 33ms tick was pure waste. Render it once into a
        # pixmap and just blit that from then on (recomputed only if the
        # widget is resized, via resizeEvent above).
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

    def _draw_scanline(self, painter: QPainter):
        c = ACCENT
        h = max(self.height(), 1)
        scan_y = (self._t * SCANLINE_SPEED_PX_PER_SEC) % h
        grad = QLinearGradient(0, scan_y - 40, 0, scan_y + 40)
        grad.setColorAt(0.0, QColor(c.red(), c.green(), c.blue(), 0))
        grad.setColorAt(0.5, QColor(c.red(), c.green(), c.blue(), 34))
        grad.setColorAt(1.0, QColor(c.red(), c.green(), c.blue(), 0))
        painter.fillRect(QRectF(0, scan_y - 40, self.width(), 80), grad)
