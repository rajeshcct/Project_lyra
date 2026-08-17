"""
Startup splash screen.

Shows assets/splash.png (your own reference image) with a fade-in, holds
briefly, then hands off to the main chat window. If that file isn't
present, falls back to a plain dark screen with the title so the app still
starts cleanly instead of crashing on a missing asset.
"""

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QRectF
from PySide6.QtGui import QPixmap, QColor, QFont
from PySide6.QtWidgets import QApplication, QSplashScreen

from theme import ACCENT, BG_DARK, TEXT_MAIN

ASSET_PATH = Path(__file__).parent / "assets" / "splash.png"
SPLASH_SIZE = (640, 360)
FADE_MS = 700
HOLD_MS = 1400


class SplashScreen(QSplashScreen):
    def __init__(self):
        super().__init__(self._load_pixmap())
        self.setWindowFlag(Qt.WindowStaysOnTopHint)
        self.setWindowOpacity(0.0)
        self._anim = None  # keep a reference so it isn't GC'd mid-fade

    def _load_pixmap(self) -> QPixmap:
        pixmap = QPixmap(str(ASSET_PATH)) if ASSET_PATH.exists() else QPixmap()
        if pixmap.isNull():
            pixmap = QPixmap(*SPLASH_SIZE)
            pixmap.fill(BG_DARK)
        else:
            pixmap = pixmap.scaled(
                *SPLASH_SIZE, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
            )
        return pixmap

    def drawContents(self, painter):
        super().drawContents(painter)

        text = "LYRA — INITIALIZING"
        text_rect = self.rect().adjusted(0, 0, -16, -14)

        font = painter.font()
        font.setBold(True)
        font.setPointSize(font.pointSize() + 1)
        font.setLetterSpacing(QFont.AbsoluteSpacing, 1.5)
        painter.setFont(font)

        # Dark backing bar behind the text so it stays legible over any part
        # of the reference photo, not just the plain-black fallback area.
        bar_height = painter.fontMetrics().height() + 20
        bar_rect = QRectF(0, self.height() - bar_height, self.width(), bar_height)
        bar_color = QColor(BG_DARK)
        bar_color.setAlpha(200)
        painter.fillRect(bar_rect, bar_color)

        # Soft shadow first, then bright text on top, for extra pop even on
        # the dark bar itself.
        painter.setPen(QColor(0, 0, 0, 180))
        painter.drawText(text_rect.adjusted(1, 1, 1, 1), Qt.AlignRight | Qt.AlignBottom, text)

        painter.setPen(TEXT_MAIN)
        painter.drawText(text_rect, Qt.AlignRight | Qt.AlignBottom, text)

        # Thin accent underline for a HUD touch.
        underline_y = self.height() - 12
        painter.setPen(ACCENT)
        metrics = painter.fontMetrics()
        text_width = metrics.horizontalAdvance(text)
        painter.drawLine(
            self.width() - 16 - text_width, underline_y,
            self.width() - 16, underline_y,
        )

    def play(self, on_finished):
        """Fade in, hold, then call on_finished() (typically: begin the
        transition into the main window)."""
        self._center_on_screen()
        self.show()
        self._anim = QPropertyAnimation(self, b"windowOpacity")
        self._anim.setDuration(FADE_MS)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.start()
        QTimer.singleShot(FADE_MS + HOLD_MS, on_finished)

    def fade_out(self, duration_ms: int, on_finished):
        """Animate opacity down to 0, then call on_finished() (typically: close())."""
        self._anim = QPropertyAnimation(self, b"windowOpacity")
        self._anim.setDuration(duration_ms)
        self._anim.setStartValue(self.windowOpacity())
        self._anim.setEndValue(0.0)
        self._anim.setEasingCurve(QEasingCurve.InCubic)
        self._anim.finished.connect(on_finished)
        self._anim.start()

    def _center_on_screen(self):
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        avail = screen.availableGeometry()
        size = self.pixmap().size()
        x = avail.x() + (avail.width() - size.width()) // 2
        y = avail.y() + (avail.height() - size.height()) // 2
        self.move(x, y)
