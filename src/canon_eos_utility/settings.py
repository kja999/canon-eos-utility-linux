"""Persistent application settings (client identity + last used paths)."""

from __future__ import annotations

import os

from PySide6.QtCore import QSettings

from .protocol import random_guid

_ORG = "canon-eos-utility-linux"
_APP = "canon-eos-utility"


class AppSettings:
    """Thin wrapper around :class:`QSettings` with typed accessors."""

    def __init__(self) -> None:
        self._settings = QSettings(_ORG, _APP)

    # -- client identity ---------------------------------------------------

    @property
    def client_name(self) -> str:
        return str(self._settings.value("client/name", "EOS Utility for Linux"))

    @client_name.setter
    def client_name(self, value: str) -> None:
        self._settings.setValue("client/name", value)

    @property
    def client_guid(self) -> bytes:
        stored = self._settings.value("client/guid")
        if stored:
            try:
                return bytes.fromhex(str(stored))
            except ValueError:
                pass
        guid = random_guid()
        self._settings.setValue("client/guid", guid.hex())
        return guid

    @client_guid.setter
    def client_guid(self, value: bytes) -> None:
        self._settings.setValue("client/guid", bytes(value).hex())

    def reset_pairing(self) -> None:
        """Forget the stored client GUID to force a fresh pairing."""
        self._settings.remove("client/guid")

    # -- miscellaneous -----------------------------------------------------

    @property
    def last_host(self) -> str:
        return str(self._settings.value("connection/last_host", "192.168.1.2"))

    @last_host.setter
    def last_host(self, value: str) -> None:
        self._settings.setValue("connection/last_host", value)

    @property
    def download_dir(self) -> str:
        default = os.path.join(os.path.expanduser("~"), "Pictures", "Canon")
        return str(self._settings.value("downloads/directory", default))

    @download_dir.setter
    def download_dir(self, value: str) -> None:
        self._settings.setValue("downloads/directory", value)

    def sync(self) -> None:
        self._settings.sync()

    # -- interface state ---------------------------------------------------

    @property
    def tools_visible(self) -> bool:
        return self._settings.value("ui/tools_visible", False, type=bool)

    @tools_visible.setter
    def tools_visible(self, value: bool) -> None:
        self._settings.setValue("ui/tools_visible", bool(value))
