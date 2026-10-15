"""Qt wrapper around the mDNS browser.

Runs the (threaded) zeroconf browser and re-emits its callbacks as Qt signals so
the GUI thread can react.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from ..discovery import ZEROCONF_AVAILABLE, MdnsDiscovery


class DiscoveryService(QObject):
    cameraFound = Signal(object)  # DiscoveredCamera
    cameraLost = Signal(str)  # instance name
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._mdns: MdnsDiscovery | None = None

    @property
    def running(self) -> bool:
        return self._mdns is not None

    def start(self) -> None:
        if self._mdns is not None:
            return
        if not ZEROCONF_AVAILABLE:
            self.failed.emit(
                "Passive discovery unavailable — install the 'zeroconf' package "
                "(pip install zeroconf) or use Scan/Connect manually."
            )
            return
        try:
            self._mdns = MdnsDiscovery(
                on_found=self.cameraFound.emit,
                on_lost=self.cameraLost.emit,
            )
            self._mdns.start()
        except Exception as exc:  # pragma: no cover - depends on the network
            self._mdns = None
            self.failed.emit(f"Could not start mDNS discovery: {exc}")

    def stop(self) -> None:
        if self._mdns is not None:
            try:
                self._mdns.stop()
            except Exception:  # pragma: no cover
                pass
            self._mdns = None
