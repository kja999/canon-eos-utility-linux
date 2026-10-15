"""Live View panel with touch-to-focus support."""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

#: Nominal sensor resolution used to translate between screen and AF
#: coordinates.  Canon's touch-AF operation expects sensor pixel coordinates.
DEFAULT_SENSOR_SIZE = (5184, 3456)


class LiveViewLabel(QLabel):
    """Displays a live view frame and reports clicks in sensor coordinates."""

    clicked = Signal(int, int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(320, 240)
        self.setAlignment(Qt.AlignCenter)
        self.setText("Live view")
        self._pixmap: QPixmap | None = None
        self._display_rect = QRect()
        self._sensor_size = DEFAULT_SENSOR_SIZE
        self._touch_rect: tuple[int, int, int, int] | None = None

    def set_sensor_size(self, width: int, height: int) -> None:
        if width > 0 and height > 0:
            self._sensor_size = (width, height)

    def set_frame(self, data: bytes) -> None:
        pixmap = QPixmap()
        if not pixmap.loadFromData(data):
            return
        self._pixmap = pixmap
        self.setText("")
        self.update()

    def set_touch_af(self, x: int, y: int, width: int, height: int) -> None:
        self._touch_rect = (x, y, width, height)
        self.update()

    def clear_frame(self) -> None:
        self._pixmap = None
        self._touch_rect = None
        self.setText("Live view")
        self.update()

    # -- painting / input --------------------------------------------------

    def resizeEvent(self, event) -> None:  # noqa: N802
        self._recompute_display_rect()
        super().resizeEvent(event)

    def _recompute_display_rect(self) -> None:
        if self._pixmap is None:
            self._display_rect = QRect()
            return
        scaled = self._pixmap.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        x = (self.width() - scaled.width()) // 2
        y = (self.height() - scaled.height()) // 2
        self._display_rect = QRect(x, y, scaled.width(), scaled.height())

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        if self._pixmap is None:
            return
        self._recompute_display_rect()
        painter = QPainter(self)
        painter.drawPixmap(self._display_rect, self._pixmap)

        if self._touch_rect is not None and self._display_rect.width() > 0:
            sensor_w, sensor_h = self._sensor_size
            x, y, width, height = self._touch_rect
            rect = self._display_rect
            left = rect.x() + int(x / sensor_w * rect.width())
            top = rect.y() + int(y / sensor_h * rect.height())
            w = max(8, int(width / sensor_w * rect.width()))
            h = max(8, int(height / sensor_h * rect.height()))
            painter.setPen(QPen(QColor("#33d17a"), 2))
            painter.drawRect(QRect(left, top, w, h))
        painter.end()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if self._pixmap is None or self._display_rect.width() == 0:
            return
        if not self._display_rect.contains(event.position().toPoint()):
            return
        rel_x = (event.position().x() - self._display_rect.x()) / self._display_rect.width()
        rel_y = (event.position().y() - self._display_rect.y()) / self._display_rect.height()
        sensor_w, sensor_h = self._sensor_size
        self.clicked.emit(int(rel_x * sensor_w), int(rel_y * sensor_h))


class LiveViewPanel(QWidget):
    liveViewToggled = Signal(bool)
    captureRequested = Signal()
    autofocusRequested = Signal()
    touchAfRequested = Signal(int, int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(10)

        header = QHBoxLayout()
        header.setSpacing(8)
        self.title = QLabel("Live View")
        self.title.setObjectName("panelTitle")
        header.addWidget(self.title)
        header.addStretch(1)
        self.live_button = QPushButton("Start live view")
        self.live_button.setCheckable(True)
        self.live_button.toggled.connect(self._on_toggled)
        header.addWidget(self.live_button)
        layout.addLayout(header)

        self.view = LiveViewLabel()
        self.view.setObjectName("liveView")
        self.view.clicked.connect(self.touchAfRequested.emit)
        layout.addWidget(self.view, 1)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.autofocus_button = QPushButton("Autofocus")
        self.autofocus_button.clicked.connect(self.autofocusRequested.emit)
        actions.addWidget(self.autofocus_button)

        self.capture_button = QPushButton("Capture")
        self.capture_button.setProperty("class", "primary")
        self.capture_button.setMinimumHeight(38)
        self.capture_button.clicked.connect(self.captureRequested.emit)
        actions.addWidget(self.capture_button, 1)
        layout.addLayout(actions)

        self.set_connected(False)

    def set_connected(self, connected: bool) -> None:
        self.live_button.setEnabled(connected)
        self.capture_button.setEnabled(connected)
        self.autofocus_button.setEnabled(connected)
        if not connected:
            self.live_button.setChecked(False)
            self.view.clear_frame()

    def set_frame(self, data: bytes) -> None:
        self.view.set_frame(data)

    def set_touch_af(self, x: int, y: int, width: int, height: int) -> None:
        self.view.set_touch_af(x, y, width, height)

    def is_live(self) -> bool:
        return self.live_button.isChecked()

    def _on_toggled(self, checked: bool) -> None:
        self.live_button.setText("Stop live view" if checked else "Start live view")
        self.liveViewToggled.emit(checked)
