"""Gallery panel: browse objects on the camera and download them."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from ..models import CameraObject
from . import theme
from .icons import image_icon, movie_icon, trash_icon
from .theme import DANGER, MUTED

_HANDLE_ROLE = Qt.UserRole + 1


class _GalleryDelegate(QStyledItemDelegate):
    """Draws a thumbnail with symmetric margins and a themed corner checkbox.

    The default icon-mode delegate reserves space on the left for the check
    indicator, which pushes the image off-centre.  Drawing it ourselves keeps
    equal padding on both sides.
    """

    PADDING = 12
    CHECK = 18
    CHECK_INSET = 8

    def paint(self, painter, option, index) -> None:  # noqa: N802 (Qt naming)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = option.rect

        if option.state & QStyle.State_Selected:
            painter.setPen(Qt.NoPen)
            tint = QColor(theme.ACCENT)
            tint.setAlpha(72)
            painter.setBrush(tint)
            painter.drawRoundedRect(rect.adjusted(2, 2, -2, -2), 6, 6)
        elif option.state & QStyle.State_MouseOver:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(theme.SURFACE_2))
            painter.drawRoundedRect(rect.adjusted(2, 2, -2, -2), 6, 6)

        inner = rect.adjusted(self.PADDING, self.PADDING, -self.PADDING, -self.PADDING)
        metrics = option.fontMetrics
        text_height = metrics.height() + 6
        icon_area = QRect(inner.x(), inner.y(), inner.width(), max(0, inner.height() - text_height))

        icon = index.data(Qt.DecorationRole)
        if isinstance(icon, QIcon) and not icon.isNull():
            pixmap = icon.pixmap(icon_area.size())
            x = icon_area.x() + (icon_area.width() - pixmap.width()) // 2
            y = icon_area.y() + (icon_area.height() - pixmap.height()) // 2
            painter.drawPixmap(x, y, pixmap)

        text = index.data(Qt.DisplayRole) or ""
        text_rect = QRect(inner.x(), icon_area.bottom() + 4, inner.width(), metrics.height())
        painter.setPen(QColor(theme.TEXT))
        elided = metrics.elidedText(str(text), Qt.ElideMiddle, text_rect.width())
        painter.drawText(text_rect, Qt.AlignHCenter | Qt.AlignVCenter, elided)

        checked = index.data(Qt.CheckStateRole) == Qt.Checked
        self._draw_checkbox(painter, self._check_rect(rect), checked)
        painter.restore()

    def _check_rect(self, rect: QRect) -> QRect:
        return QRect(
            rect.x() + self.CHECK_INSET,
            rect.y() + self.CHECK_INSET,
            self.CHECK,
            self.CHECK,
        )

    def _draw_checkbox(self, painter: QPainter, box: QRect, checked: bool) -> None:
        painter.setRenderHint(QPainter.Antialiasing, True)
        if checked:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(theme.ACCENT))
            painter.drawRoundedRect(box, 4, 4)
            pen = QPen(QColor(theme.ON_ACCENT))
            pen.setWidth(2)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            painter.setPen(pen)
            path = QPainterPath()
            path.moveTo(box.left() + 4, box.center().y() + 1)
            path.lineTo(box.center().x() - 1, box.bottom() - 4)
            path.lineTo(box.right() - 4, box.top() + 4)
            painter.drawPath(path)
        else:
            painter.setBrush(QColor(theme.SURFACE_2))
            painter.setPen(QPen(QColor(theme.BORDER_STRONG), 1))
            painter.drawRoundedRect(box, 4, 4)

    def editorEvent(self, event, model, option, index) -> bool:  # noqa: N802
        if (
            event.type() == QEvent.MouseButtonRelease
            and event.button() == Qt.LeftButton
            and self._check_rect(option.rect).contains(event.position().toPoint())
        ):
            checked = index.data(Qt.CheckStateRole) == Qt.Checked
            model.setData(
                index,
                Qt.Unchecked if checked else Qt.Checked,
                Qt.CheckStateRole,
            )
            return True
        return super().editorEvent(event, model, option, index)


class GalleryPanel(QWidget):
    downloadRequested = Signal(object)
    refreshRequested = Signal()
    #: Emitted with a list of object handles to delete from the camera.
    deleteRequested = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._directory = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(10)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refreshRequested.emit)
        toolbar.addWidget(self.refresh_button)

        self.select_all_button = QPushButton("Select all")
        self.select_all_button.clicked.connect(lambda: self._set_all_checked(True))
        toolbar.addWidget(self.select_all_button)

        self.select_none_button = QPushButton("Select none")
        self.select_none_button.clicked.connect(lambda: self._set_all_checked(False))
        toolbar.addWidget(self.select_none_button)

        self.download_selected_button = QPushButton("Download selected")
        self.download_selected_button.clicked.connect(self._download_selected)
        toolbar.addWidget(self.download_selected_button)

        self.download_all_button = QPushButton("Download all")
        self.download_all_button.clicked.connect(self._download_all)
        toolbar.addWidget(self.download_all_button)

        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        self.list = QListWidget()
        self.list.setViewMode(QListWidget.IconMode)
        self.list.setResizeMode(QListWidget.Adjust)
        self.list.setMovement(QListWidget.Static)
        self.list.setIconSize(self.list.iconSize().expandedTo(_icon_size()))
        self.list.setGridSize(_grid_size())
        self.list.setWordWrap(True)
        self.list.setSelectionMode(QListWidget.ExtendedSelection)
        self.list.setMouseTracking(True)
        self.list.viewport().setMouseTracking(True)
        self.list.setItemDelegate(_GalleryDelegate(self.list))
        self.list.itemDoubleClicked.connect(lambda _: self._download_selected())
        self.list.itemSelectionChanged.connect(self._update_delete_enabled)
        self.list.itemChanged.connect(lambda _item: self._update_delete_enabled())
        layout.addWidget(self.list, 1)

        actions_row = QHBoxLayout()
        self.delete_button = QPushButton("Delete")
        self.delete_button.setProperty("class", "danger")
        self.delete_button.setIcon(trash_icon(DANGER, 16))
        self.delete_button.setToolTip("Delete the selected files from the camera")
        self.delete_button.setEnabled(False)
        self.delete_button.clicked.connect(self._delete_selected)
        actions_row.addWidget(self.delete_button)
        actions_row.addStretch(1)
        layout.addLayout(actions_row)

        status_row = QHBoxLayout()
        self.summary_label = QLabel("Not connected")
        status_row.addWidget(self.summary_label)
        status_row.addStretch(1)
        self.directory_label = QLabel("")
        self.directory_label.setProperty("class", "muted")
        status_row.addWidget(self.directory_label)
        layout.addLayout(status_row)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self._items: dict[int, QListWidgetItem] = {}
        self._connected = False

    # -- public API --------------------------------------------------------

    def set_directory(self, directory: str) -> None:
        self._directory = directory
        self.directory_label.setText(f"Save to: {directory}")

    def set_connected(self, connected: bool) -> None:
        self._connected = connected
        for button in (
            self.refresh_button,
            self.select_all_button,
            self.select_none_button,
            self.download_selected_button,
            self.download_all_button,
        ):
            button.setEnabled(connected)
        self._update_delete_enabled()
        if not connected:
            self.clear()

    def _update_delete_enabled(self) -> None:
        self.delete_button.setEnabled(self._connected and bool(self.selected_handles()))

    def clear(self) -> None:
        self.list.clear()
        self._items.clear()
        self.summary_label.setText("Not connected")
        self._update_delete_enabled()

    def set_objects(self, objects: list[CameraObject]) -> None:
        self.list.clear()
        self._items.clear()
        for obj in objects:
            item = QListWidgetItem(obj.filename or f"0x{obj.handle:08X}")
            # Stored as a string: Canon handles are unsigned 32-bit and would
            # overflow Qt's signed int QVariant conversion.
            item.setData(_HANDLE_ROLE, str(obj.handle))
            # Check state is handled by _GalleryDelegate (which draws its own
            # checkbox); leave the flag off so the view does not also toggle it.
            item.setCheckState(Qt.Unchecked)
            # Fill the grid cell so the whole thumbnail area is clickable even
            # when there is no preview image yet.
            item.setSizeHint(_cell_size())
            item.setIcon(
                movie_icon(MUTED, _placeholder_size())
                if obj.is_movie
                else image_icon(MUTED, _placeholder_size())
            )
            item.setToolTip(
                f"{obj.filename}\n{obj.format_name} · {_human_size(obj.size)}\n"
                f"{obj.width}×{obj.height}\n{obj.capture_date_display}"
            )
            item.setTextAlignment(Qt.AlignHCenter)
            self.list.addItem(item)
            self._items[obj.handle] = item
        self.summary_label.setText(f"{len(objects)} objects")

    def set_thumbnail(self, handle: int, data: bytes) -> None:
        item = self._items.get(handle)
        if item is None:
            return
        pixmap = QPixmap()
        if pixmap.loadFromData(data):
            item.setIcon(QIcon(pixmap))

    def set_progress(self, done: int, total: int, label: str) -> None:
        if total <= 0:
            return
        if label:
            self.summary_label.setText(f"Downloading {label} ({done}/{total})")
        if done >= total:
            self.progress.setVisible(False)

    def set_file_progress(self, done: int, total: int) -> None:
        if total <= 0:
            self.progress.setVisible(False)
            return
        self.progress.setVisible(True)
        self.progress.setMaximum(total)
        self.progress.setValue(done)

    def selected_handles(self) -> list[int]:
        handles: list[int] = []
        for index in range(self.list.count()):
            item = self.list.item(index)
            if item.checkState() == Qt.Checked or item.isSelected():
                handles.append(self._handle_of(item))
        return handles

    def all_handles(self) -> list[int]:
        return [self._handle_of(self.list.item(i)) for i in range(self.list.count())]

    @staticmethod
    def _handle_of(item: QListWidgetItem) -> int:
        return int(item.data(_HANDLE_ROLE))

    # -- internals ---------------------------------------------------------

    def choose_directory(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Download folder", self._directory)
        if directory:
            self.set_directory(directory)

    def _set_all_checked(self, checked: bool) -> None:
        state = Qt.Checked if checked else Qt.Unchecked
        for index in range(self.list.count()):
            self.list.item(index).setCheckState(state)

    def _download_selected(self) -> None:
        handles = self.selected_handles()
        if handles:
            self.downloadRequested.emit(handles)

    def _download_all(self) -> None:
        handles = self.all_handles()
        if handles:
            self.downloadRequested.emit(handles)

    def _delete_selected(self) -> None:
        handles = self.selected_handles()
        if handles:
            self.deleteRequested.emit(handles)

    def contextMenuEvent(self, event) -> None:  # noqa: N802 (Qt naming)
        from PySide6.QtWidgets import QMenu

        position = event.globalPosition().toPoint()
        item = self.list.itemAt(self.list.viewport().mapFromGlobal(position))
        if item is None:
            return
        menu = QMenu(self)
        download_action = menu.addAction("Download")
        delete_action = menu.addAction("Delete from camera")
        chosen = menu.exec(position)
        handle = self._handle_of(item)
        if chosen is download_action:
            self.downloadRequested.emit([handle])
        elif chosen is delete_action:
            self.deleteRequested.emit([handle])


def _human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if value < 1024 or unit == "GiB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{size} B"


def _icon_size():
    return QSize(140, 140)


def _grid_size():
    return QSize(186, 206)


def _cell_size():
    return QSize(176, 196)


def _placeholder_size():
    return 140
