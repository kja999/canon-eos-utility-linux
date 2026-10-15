"""Main application window."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QMainWindow,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..config import AppConfig
from ..models import CameraInfo
from ..protocol import random_guid
from ..settings import AppSettings
from .camera_worker import CameraWorker
from .connection_bar import ConnectionBar
from .control_panel import ControlPanel
from .dialogs import ConfirmDialog, MessageDialog
from .discovery_service import DiscoveryService
from .gallery_panel import GalleryPanel
from .icons import app_icon
from .live_view_panel import LiveViewPanel
from .settings_dialog import SettingsDialog
from .theme import apply_theme, apply_widget_theme


class MainWindow(QMainWindow):
    def __init__(self, enable_discovery: bool = True) -> None:
        super().__init__()
        self.setWindowTitle("Canon EOS Utility")
        self.setWindowIcon(app_icon())
        self.resize(1180, 720)

        self.settings = AppSettings()
        self.config = AppConfig.load()
        self._ensure_identity()
        self.worker = CameraWorker(
            client_name=self.config.client_name,
            client_guid=bytes.fromhex(self.config.client_guid),
        )
        self.worker.set_config(self.config)
        self.worker.start()

        self.discovery = DiscoveryService(self)

        self._connected = False
        self._connecting = False

        self._build_ui()
        self._build_menu()
        self._connect_signals()

        self.connection_bar.set_host(self.settings.last_host)
        self.connection_bar.set_auto_connect(self.config.auto_connect)
        self.gallery.set_directory(self.config.resolved_download_directory())
        self.statusBar().showMessage("Ready")

        apply_widget_theme(self, self.config.accent_color)

        if enable_discovery:
            self.discovery.start()

    def _ensure_identity(self) -> None:
        """Keep the pairing identity in the TOML config, migrating from QSettings."""
        if not self.config.client_guid:
            self.config.client_guid = self.settings.client_guid.hex()
        if not self.config.client_name:
            self.config.client_name = self.settings.client_name
        self.config.save()

    # -- UI construction ---------------------------------------------------
    def _build_ui(self) -> None:
        self.connection_bar = ConnectionBar()
        self.gallery = GalleryPanel()
        self.live_view = LiveViewPanel()
        self.controls = ControlPanel()

        right = QSplitter(Qt.Vertical)
        right.addWidget(self.live_view)
        right.addWidget(self.controls)
        right.setStretchFactor(0, 2)
        right.setStretchFactor(1, 1)
        right.setChildrenCollapsible(False)
        self.right_panel = right

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self.gallery)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setChildrenCollapsible(False)
        self.splitter = splitter

        body = QHBoxLayout()
        body.setContentsMargins(10, 10, 0, 10)
        body.setSpacing(10)
        body.addWidget(splitter, 1)
        body.addWidget(self._build_tool_rail())

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.connection_bar)
        layout.addLayout(body, 1)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        self._set_tools_visible(self.settings.tools_visible)

        self.gallery.set_connected(False)
        self.live_view.set_connected(False)
        self.controls.set_connected(False)

    def _build_tool_rail(self) -> QWidget:
        """A slim right-hand rail that reveals the Live View / controls panel."""
        rail = QWidget()
        rail.setObjectName("toolRail")
        rail.setFixedWidth(58)

        layout = QVBoxLayout(rail)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(8)

        self.tools_button = QToolButton()
        self.tools_button.setText("Tools")
        self.tools_button.setCheckable(True)
        self.tools_button.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.tools_button.setToolTip("Show or hide Live View and camera controls")
        self.tools_button.toggled.connect(self._set_tools_visible)
        layout.addWidget(self.tools_button)
        layout.addStretch(1)
        return rail

    def _set_tools_visible(self, visible: bool) -> None:
        self.right_panel.setVisible(visible)
        if self.tools_button.isChecked() != visible:
            self.tools_button.setChecked(visible)
        if hasattr(self, "tools_action"):
            self.tools_action.setChecked(visible)
        if visible and hasattr(self, "splitter"):
            width = max(self.splitter.width(), 1)
            self.splitter.setSizes([int(width * 0.6), int(width * 0.4)])
        self.settings.tools_visible = visible

    def _build_menu(self) -> None:
        menu = self.menuBar()

        file_menu = menu.addMenu("&File")
        folder_action = QAction("Choose download folder…", self)
        folder_action.triggered.connect(self._choose_folder)
        file_menu.addAction(folder_action)
        settings_action = QAction("Settings…", self)
        settings_action.setShortcut("Ctrl+,")
        settings_action.triggered.connect(self._open_settings)
        file_menu.addAction(settings_action)
        file_menu.addSeparator()
        quit_action = QAction("Quit", self)
        quit_action.setShortcut(QKeySequence.Quit)
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        camera_menu = menu.addMenu("&Camera")
        self.connect_action = QAction("Connect", self)
        self.connect_action.triggered.connect(lambda: self._connect())
        camera_menu.addAction(self.connect_action)
        self.disconnect_action = QAction("Disconnect", self)
        self.disconnect_action.triggered.connect(self.worker.disconnect_camera)
        camera_menu.addAction(self.disconnect_action)
        refresh_action = QAction("Refresh contents", self)
        refresh_action.setShortcut(QKeySequence.Refresh)
        refresh_action.triggered.connect(self.worker.refresh_gallery)
        camera_menu.addAction(refresh_action)
        camera_menu.addSeparator()
        pairing_action = QAction("Reset pairing (new client identity)", self)
        pairing_action.triggered.connect(self._reset_pairing)
        camera_menu.addAction(pairing_action)

        view_menu = menu.addMenu("&View")
        self.tools_action = QAction("Live View & controls panel", self)
        self.tools_action.setCheckable(True)
        self.tools_action.setShortcut("Ctrl+T")
        self.tools_action.setChecked(self.settings.tools_visible)
        self.tools_action.toggled.connect(self._set_tools_visible)
        view_menu.addAction(self.tools_action)
        refresh_view = QAction("Refresh contents", self)
        refresh_view.setShortcut(QKeySequence.Refresh)
        refresh_view.triggered.connect(self.worker.refresh_gallery)
        view_menu.addAction(refresh_view)

        help_menu = menu.addMenu("&Help")
        about_action = QAction("About", self)
        about_action.triggered.connect(self._about)
        help_menu.addAction(about_action)

    def _connect_signals(self) -> None:
        self.connection_bar.connectRequested.connect(self._connect)
        self.connection_bar.disconnectRequested.connect(self._disconnect)

        self.gallery.refreshRequested.connect(self.worker.refresh_gallery)
        self.gallery.downloadRequested.connect(self._download)
        self.gallery.deleteRequested.connect(self._confirm_delete)

        self.live_view.liveViewToggled.connect(self.worker.set_live_view)
        self.live_view.captureRequested.connect(self.worker.capture)
        self.live_view.autofocusRequested.connect(self.worker.autofocus)
        self.live_view.touchAfRequested.connect(self.worker.touch_af)

        self.controls.propertyChangeRequested.connect(self.worker.set_property)

        self.worker.connected.connect(self._on_connected)
        self.worker.deviceInfo.connect(self._on_device_info)
        self.worker.disconnected.connect(self._on_disconnected)
        self.worker.connectionFailed.connect(self._on_connection_failed)
        self.worker.errorOccurred.connect(self._on_error)
        self.worker.statusChanged.connect(self.statusBar().showMessage)

        self.worker.propertiesChanged.connect(self._on_properties_changed)
        self.worker.allowedValuesChanged.connect(self._on_allowed_values_changed)

        self.worker.objectsLoaded.connect(self.gallery.set_objects)
        self.worker.thumbnailReady.connect(self.gallery.set_thumbnail)
        self.worker.objectAdded.connect(self._on_object_added)

        self.worker.downloadProgress.connect(self.gallery.set_progress)
        self.worker.downloadBytes.connect(self.gallery.set_file_progress)
        self.worker.downloadFinished.connect(
            lambda total: self.statusBar().showMessage(f"Downloaded {total} file(s)")
        )
        self.worker.downloadsCompleted.connect(self._on_downloads_completed)
        self.worker.fileExists.connect(self._on_file_exists)
        self.worker.filesDeleted.connect(
            lambda count: self.statusBar().showMessage(
                f"Deleted {count} file(s) from the camera", 6000
            )
        )

        self.worker.liveViewFrame.connect(self.live_view.set_frame)
        self.worker.liveViewTouchAf.connect(self.live_view.set_touch_af)
        self.worker.captureCompleted.connect(
            lambda: self.statusBar().showMessage("Capture complete")
        )

        self.discovery.cameraFound.connect(self._on_camera_found)
        self.discovery.cameraLost.connect(self._on_camera_lost)
        self.discovery.failed.connect(self.statusBar().showMessage)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self.worker.refresh_gallery)

    # -- actions -----------------------------------------------------------

    def _connect(self) -> None:
        host = self.connection_bar.current_host()
        if not host:
            self.statusBar().showMessage("Enter a camera address first")
            return
        self._start_connection(host)

    def _start_connection(self, host: str) -> None:
        self.settings.last_host = host
        self._connecting = True
        self.worker.connect_camera(host)

    def _disconnect(self) -> None:
        self.worker.disconnect_camera()

    def _on_camera_found(self, camera) -> None:
        host = camera.address if camera.port == 15740 else f"{camera.address}:{camera.port}"
        self.connection_bar.set_host(host)
        self.statusBar().showMessage(f"Detected camera {camera.display_name} at {host}")
        if self.connection_bar.auto_connect() and not self._connected and not self._connecting:
            self.statusBar().showMessage(f"Camera detected at {host} — connecting…")
            self._start_connection(host)

    def _on_camera_lost(self, instance: str) -> None:
        if not self._connected:
            self.statusBar().showMessage(f"Camera {instance} left the network", 5000)

    def _download(self, handles: list[int]) -> None:
        if not handles:
            return
        directory = self.config.resolved_download_directory()
        self.gallery.set_directory(directory)
        self.worker.download_objects(handles, directory)

    def _open_settings(self) -> None:
        dialog = SettingsDialog(self.config, self)
        if dialog.exec() == QDialog.Accepted:
            self.config = dialog.result_config()
            self.config.save()
            self._apply_config()

    def _apply_config(self) -> None:
        self.worker.set_config(self.config)
        self.connection_bar.set_auto_connect(self.config.auto_connect)
        self.gallery.set_directory(self.config.resolved_download_directory())
        app = QApplication.instance()
        if app is not None:
            apply_theme(app, self.config.accent_color)
        apply_widget_theme(self, self.config.accent_color)
        self.statusBar().showMessage("Settings saved", 4000)

    def _on_file_exists(self, conflict) -> None:
        """Ask whether to overwrite an existing destination file."""
        confirmed, apply_all = ConfirmDialog.ask(
            self,
            "File exists",
            "File exists. Overwrite?",
            detail=conflict.target,
            checkbox_text="Apply to all files in this sync",
            yes_text="Overwrite",
            no_text="Skip",
        )
        conflict.overwrite = confirmed
        conflict.apply_to_all = apply_all
        conflict.event.set()

    def _on_downloads_completed(self, objects) -> None:
        """Offer to delete the freshly downloaded files from the camera."""
        handles = [obj.handle for obj in objects]
        if not handles:
            return
        if self.config.delete_after_download:
            self.worker.delete_objects(handles)
            return

        confirmed, always = ConfirmDialog.ask(
            self,
            "Download complete",
            "Download complete. Delete files from the camera?",
            detail=f"{len(handles)} file(s) downloaded and verified.",
            checkbox_text="Always delete files after download",
            force_yes_when_checked=True,
            destructive=True,
            yes_text="Delete",
            no_text="Keep",
        )
        if always:
            self.config.delete_after_download = True
            self.config.save()
        if confirmed:
            self.worker.delete_objects(handles)

    def _confirm_delete(self, handles) -> None:
        handles = list(handles)
        if not handles:
            return
        count = len(handles)
        noun = "photo" if count == 1 else "photos"
        confirmed, _ = ConfirmDialog.ask(
            self,
            "Delete files",
            f"Delete {count} selected {noun}?",
            detail="They will be permanently removed from the camera.",
            destructive=True,
            yes_text="Delete",
            no_text="Cancel",
        )
        if confirmed:
            self.worker.delete_objects(handles)

    def _choose_folder(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self, "Download folder", self.config.resolved_download_directory()
        )
        if directory:
            self.config.download_directory = directory
            self.config.save()
            self.gallery.set_directory(self.config.resolved_download_directory())

    def _reset_pairing(self) -> None:
        self.settings.reset_pairing()
        guid = random_guid()
        self.config.client_guid = guid.hex()
        self.config.save()
        self.worker.set_identity(self.config.client_name, guid)
        MessageDialog.show_message(
            self,
            "Pairing reset",
            "A new client identity was generated.",
            detail=("The camera may ask you to confirm the pairing again on the next connection."),
        )

    def _about(self) -> None:
        MessageDialog.show_message(
            self,
            "About Canon EOS Utility",
            "<b>Canon EOS Utility for Linux</b><br>"
            "Wireless PTP/IP client for Canon EOS cameras.<br><br>"
            "Browse the memory card, download photos, control the camera and "
            "use Live View over WiFi.",
            rich=True,
        )

    # -- worker callbacks --------------------------------------------------

    def _on_connected(self, info: CameraInfo) -> None:
        self._connected = True
        self._connecting = False
        self.connection_bar.set_connected(True)
        self.gallery.set_connected(True)
        self.live_view.set_connected(True)
        self.controls.set_connected(True)
        self.setWindowTitle(f"Canon EOS Utility — {info.display_name}")
        self.connect_action.setEnabled(False)
        self.disconnect_action.setEnabled(True)

    def _on_device_info(self, info) -> None:
        if info.model:
            self.statusBar().showMessage(
                f"{info.manufacturer} {info.model} (firmware {info.device_version})"
            )

    def _on_disconnected(self) -> None:
        self._connected = False
        self._connecting = False
        self.connection_bar.set_connected(False)
        self.gallery.set_connected(False)
        self.live_view.set_connected(False)
        self.controls.set_connected(False)
        self.setWindowTitle("Canon EOS Utility")
        self.connect_action.setEnabled(True)
        self.disconnect_action.setEnabled(False)

    def _on_error(self, message: str) -> None:
        self.statusBar().showMessage(message, 8000)

    def _on_connection_failed(self, message: str) -> None:
        self._on_disconnected()
        MessageDialog.show_message(
            self,
            "Connection failed",
            message,
            detail=(
                "Check that the camera is on the 'Remote control (EOS Utility)' "
                "Wi-Fi screen, that it is in camera access-point or infrastructure "
                "mode, and that both devices are on the same network. The camera "
                "may ask you to confirm the pairing again."
            ),
        )

    def _on_properties_changed(self, changed: dict) -> None:
        for code, value in changed.items():
            self.controls.update_property(code, value)

    def _on_allowed_values_changed(self, changes: dict) -> None:
        for code, values in changes.items():
            self.controls.update_allowed_values(code, values)

    def _on_object_added(self, _handle: int) -> None:
        self._refresh_timer.start(400)

    # -- shutdown ----------------------------------------------------------

    def closeEvent(self, event) -> None:  # noqa: N802
        self.discovery.stop()
        self.worker.stop()
        self.settings.sync()
        super().closeEvent(event)
