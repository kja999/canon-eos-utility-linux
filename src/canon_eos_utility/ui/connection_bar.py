"""Connection toolbar: discovery, host entry and connect/disconnect."""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

from ..discovery import DiscoveredCamera, discover


class _DiscoveryThread(QThread):
    found = Signal(object)

    def __init__(self, timeout: float = 3.0) -> None:
        super().__init__()
        self._timeout = timeout

    def run(self) -> None:  # pragma: no cover - network dependent
        try:
            cameras = discover(self._timeout)
        except Exception:
            cameras = []
        self.found.emit(cameras)


class ConnectionBar(QWidget):
    connectRequested = Signal(str)
    disconnectRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._connected = False
        self._discovery: _DiscoveryThread | None = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)
        self.setObjectName("connectionBar")

        label = QLabel("Camera")
        label.setProperty("class", "muted")
        layout.addWidget(label)
        self.host_combo = QComboBox()
        self.host_combo.setEditable(True)
        self.host_combo.setMinimumWidth(240)
        self.host_combo.setInsertPolicy(QComboBox.NoInsert)
        self.host_combo.lineEdit().setPlaceholderText("Camera address (host or host:port)")
        layout.addWidget(self.host_combo)

        self.scan_button = QPushButton("Scan network")
        self.scan_button.clicked.connect(self._scan)
        layout.addWidget(self.scan_button)

        self.connect_button = QPushButton("Connect")
        self.connect_button.setProperty("class", "primary")
        self.connect_button.clicked.connect(self._toggle)
        layout.addWidget(self.connect_button)

        self.auto_connect_checkbox = QCheckBox("Auto-connect")
        self.auto_connect_checkbox.setChecked(True)
        self.auto_connect_checkbox.setToolTip(
            "Connect automatically as soon as the camera announces itself via mDNS"
        )
        layout.addWidget(self.auto_connect_checkbox)

        layout.addStretch(1)

    # -- public API --------------------------------------------------------

    def auto_connect(self) -> bool:
        return self.auto_connect_checkbox.isChecked()

    def set_auto_connect(self, enabled: bool) -> None:
        self.auto_connect_checkbox.setChecked(enabled)

    def set_host(self, host: str) -> None:
        if host and self.host_combo.findText(host) == -1:
            self.host_combo.addItem(host)
        self.host_combo.setCurrentText(host)

    def current_host(self) -> str:
        return self.host_combo.currentText().strip()

    def set_connected(self, connected: bool) -> None:
        self._connected = connected
        self.connect_button.setText("Disconnect" if connected else "Connect")
        self.host_combo.setEnabled(not connected)
        self.scan_button.setEnabled(not connected)

    def set_busy(self, busy: bool) -> None:
        self.scan_button.setEnabled(not busy and not self._connected)
        if not self._connected:
            self.connect_button.setEnabled(not busy)

    # -- internals ---------------------------------------------------------

    def _toggle(self) -> None:
        if self._connected:
            self.disconnectRequested.emit()
        else:
            host = self.current_host()
            if host:
                self.connectRequested.emit(host)

    def _scan(self) -> None:
        if self._discovery is not None and self._discovery.isRunning():
            return
        self.scan_button.setEnabled(False)
        self.scan_button.setText("Scanning…")
        self._discovery = _DiscoveryThread(timeout=3.0)
        self._discovery.found.connect(self._on_found)
        self._discovery.finished.connect(self._on_scan_finished)
        self._discovery.start()

    def _on_found(self, cameras: list[DiscoveredCamera]) -> None:
        for camera in cameras:
            label = f"{camera.display_name} ({camera.address})"
            if self.host_combo.findText(camera.address) == -1:
                self.host_combo.addItem(camera.address)
            index = self.host_combo.findText(camera.address)
            self.host_combo.setItemText(index, camera.address)
            self.host_combo.setItemData(index, label)
        if cameras:
            self.host_combo.setCurrentText(cameras[0].address)

    def _on_scan_finished(self) -> None:
        self.scan_button.setText("Scan network")
        self.scan_button.setEnabled(not self._connected)
