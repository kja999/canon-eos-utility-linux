"""canon-eos-utility: Qt client for Canon EOS cameras over WiFi (PTP/IP)."""

from __future__ import annotations

__version__ = "0.1.0"

#: Reverse-DNS application id (matches the .desktop file / Flatpak app id).
APP_ID = "org.problem_child.CanonEOSUtility"
#: Human readable application name.
APP_NAME = "Canon EOS Utility"
#: Author credited on the splash screen.
APP_AUTHOR = "Chris Roberts"

__all__ = ["__version__", "APP_ID", "APP_NAME", "APP_AUTHOR"]
