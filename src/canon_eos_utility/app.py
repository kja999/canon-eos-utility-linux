"""QApplication bootstrap."""

from __future__ import annotations

import ctypes
import sys

from PySide6.QtWidgets import QApplication

from . import APP_ID, APP_NAME
from .config import AppConfig
from .ui.icons import app_icon
from .ui.main_window import MainWindow
from .ui.theme import apply_theme


def _set_process_name(name: str) -> None:
    """Set the process name shown by ``ps`` / system monitors (best effort)."""
    try:
        libc = ctypes.CDLL("libc.so.6", use_errno=True)
        # PR_SET_NAME = 15; limited to 15 characters plus NUL.
        libc.prctl(15, name.encode("utf-8"), 0, 0, 0)
    except Exception:  # pragma: no cover - platform dependent
        pass


def run(argv: list[str] | None = None) -> int:
    _set_process_name("canon-eos-utility")
    app = QApplication.instance() or QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName("canon-eos-utility-linux")
    # Match the installed desktop file so the compositor shows the app name and
    # icon in the taskbar / alt-tab list instead of "python3".
    app.setDesktopFileName(APP_ID)
    app.setWindowIcon(app_icon())
    apply_theme(app, AppConfig.load().accent_color)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(run())
