"""Start-up splash screen.

A small, frameless card showing the application mark, name and author while the
main window is being built.  It follows the app's dark theme and fades out on its
own after a short, fixed time so it never holds the user up.

The fade is done with a graphics effect on the card rather than window opacity,
because the Wayland platform plugin does not support per-window opacity.
"""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from .. import APP_AUTHOR, APP_NAME, __version__
from .icons import app_logo

#: How long the splash stays on screen, in milliseconds (fade-out included).
SPLASH_DURATION_MS = 1000
#: Fade-in and fade-out durations, in milliseconds.
_FADE_IN_MS = 150
_FADE_OUT_MS = 250


class SplashScreen(QWidget):
    """Frameless, self-dismissing start-up splash."""

    def __init__(self, duration_ms: int = SPLASH_DURATION_MS) -> None:
        super().__init__(None, Qt.SplashScreen | Qt.FramelessWindowHint)
        self._duration_ms = duration_ms
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setObjectName("splashRoot")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self._card = QFrame()
        self._card.setObjectName("splashCard")
        outer.addWidget(self._card)
        self._build(self._card)

        self._effect = QGraphicsOpacityEffect(self._card)
        self._effect.setOpacity(1.0)
        self._card.setGraphicsEffect(self._effect)

        self._fade_in = QPropertyAnimation(self._effect, b"opacity", self)
        self._fade_in.setDuration(_FADE_IN_MS)
        self._fade_in.setStartValue(0.0)
        self._fade_in.setEndValue(1.0)
        self._fade_in.setEasingCurve(QEasingCurve.OutCubic)

        self._fade_out = QPropertyAnimation(self._effect, b"opacity", self)
        self._fade_out.setDuration(_FADE_OUT_MS)
        self._fade_out.setStartValue(1.0)
        self._fade_out.setEndValue(0.0)
        self._fade_out.setEasingCurve(QEasingCurve.InCubic)
        self._fade_out.finished.connect(self.close)

    def _build(self, card: QFrame) -> None:
        layout = QVBoxLayout(card)
        layout.setContentsMargins(56, 48, 56, 44)
        layout.setSpacing(16)

        logo = QLabel()
        logo.setPixmap(app_logo(148))
        logo.setAlignment(Qt.AlignCenter)

        title = QLabel(APP_NAME)
        title.setObjectName("splashTitle")
        title.setAlignment(Qt.AlignCenter)

        author = QLabel(APP_AUTHOR)
        author.setObjectName("splashAuthor")
        author.setAlignment(Qt.AlignCenter)

        version = QLabel(f"Version {__version__}")
        version.setObjectName("splashVersion")
        version.setAlignment(Qt.AlignCenter)

        for widget in (logo, title, author, version):
            layout.addWidget(widget)

    def _center_on_screen(self) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        geometry = screen.availableGeometry()
        self.move(geometry.center() - self.rect().center())

    def start(self) -> None:
        """Show the splash and schedule its fade-out."""
        self.adjustSize()
        self._center_on_screen()
        self._effect.setOpacity(0.0)
        self.show()
        self._fade_in.start()
        QTimer.singleShot(max(0, self._duration_ms - _FADE_OUT_MS), self._fade_out.start)
