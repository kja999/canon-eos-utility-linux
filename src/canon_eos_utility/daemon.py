"""Headless auto-sync daemon.

Watches for Canon cameras over mDNS and, whenever one appears, connects and
downloads all of its photos and movies into the configured folder using the
file-naming template.  New files are imported while the camera stays connected;
if it disappears, the daemon keeps watching and resumes on the next
announcement.

Run it with ``canon-eos-daemon`` or ``python -m canon_eos_utility.daemon``.
It has no Qt dependency, so it can run under systemd without a display.
"""

from __future__ import annotations

import argparse
import os
import queue
import signal
import sys
import threading
import time
from datetime import datetime

from .config import AppConfig
from .constants import PTPIP_PORT
from .discovery import ZEROCONF_AVAILABLE, MdnsDiscovery
from .exceptions import CameraError
from .protocol import CameraClient, TransportError, random_guid
from .sync import (
    POLICY_ASK,
    POLICY_OVERWRITE,
    POLICY_SKIP,
    CameraSync,
    SyncState,
)

CONNECT_ATTEMPTS = 40
CONNECT_RETRY_DELAY = 0.5
CONNECT_TIMEOUT = 2.0
STATE_FILENAME = ".canon-eos-sync.json"


def _default_log(message: str) -> None:
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {message}", flush=True)


def _split_host_port(value: str) -> tuple[str, int]:
    value = value.strip()
    if value.count(":") == 1:
        host, _, port = value.partition(":")
        if port.isdigit():
            return host, int(port)
    return value, PTPIP_PORT


class CameraDaemon:
    """Continuously discover cameras and sync their contents to disk."""

    def __init__(
        self,
        config: AppConfig,
        host: str | None = None,
        once: bool = False,
        interval: float | None = None,
        log=None,
        overwrite_policy: str | None = None,
        delete_after: bool | None = None,
    ) -> None:
        self.config = config
        self.host = host
        self.once = once
        self.interval = interval if interval is not None else config.daemon_poll_interval
        self.log = log or _default_log
        self.directory = config.resolved_download_directory()

        self.overwrite_policy = overwrite_policy or (
            POLICY_OVERWRITE if config.always_overwrite else POLICY_ASK
        )
        self.delete_after = config.delete_after_download if delete_after is None else delete_after
        self._current_policy = self.overwrite_policy

        self._stop = threading.Event()
        self._state = SyncState(os.path.join(self.directory, STATE_FILENAME))
        self._discovery: MdnsDiscovery | None = None

    # -- lifecycle ---------------------------------------------------------

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> int:
        self._install_signal_handlers()
        os.makedirs(self.directory, exist_ok=True)
        self._ensure_identity()

        self.log(f"Download folder: {self.directory}")
        self.log(f"Naming template: {self.config.filename_template}")

        targets: queue.Queue = queue.Queue()
        if self.host:
            targets.put(_split_host_port(self.host))
        else:
            if not ZEROCONF_AVAILABLE:
                self.log(
                    "mDNS discovery unavailable (install 'zeroconf'); "
                    "use --host for a fixed address"
                )
                return 1
            self._discovery = MdnsDiscovery(
                on_found=lambda camera: targets.put((camera.address, camera.port))
            )
            self._discovery.start()
            self.log("Watching for Canon cameras over mDNS (_ptp._tcp)…")

        try:
            while not self._stop.is_set():
                try:
                    address, port = targets.get(timeout=1.0)
                except queue.Empty:
                    continue
                self.log(f"Camera seen at {address}:{port}")
                self._run_session(address, port)
                if self.once:
                    break
        finally:
            if self._discovery is not None:
                self._discovery.stop()
        self.log("Stopped")
        return 0

    # -- one connected session --------------------------------------------

    def _run_session(self, address: str, port: int) -> None:
        client = self._connect(address, port)
        if client is None:
            self.log("Could not connect; will retry on the next announcement")
            return

        try:
            device = client.get_device_info()
            context = {
                "model": device.model or (client.info.name if client.info else ""),
                "manufacturer": device.manufacturer,
                "serial": device.serial_number,
                "firmware": device.device_version,
                "name": client.info.name if client.info else "",
            }
            self.log(f"Connected to {context['model'] or context['name']}")

            saved: list = []
            sync = CameraSync(
                client,
                self.config,
                context,
                log=self.log,
                stop=self._stop,
                policy=self.overwrite_policy,
                ask=self._ask_overwrite,
                on_downloaded=saved.append,
            )
            self._sync_once(sync)
            self._maybe_delete(client, saved)
            if self.once:
                return

            while not self._stop.is_set():
                if self._stop.wait(self.interval):
                    break
                try:
                    self._sync_once(sync)
                    self._maybe_delete(client, saved)
                except (CameraError, TransportError) as exc:
                    self.log(f"Connection lost ({exc}); waiting for the camera to return")
                    return
        except (CameraError, TransportError) as exc:
            self.log(f"Lost connection: {exc}")
        finally:
            try:
                client.disconnect()
            except Exception:  # pragma: no cover - defensive
                pass

    def _sync_once(self, sync: CameraSync) -> None:
        downloaded, skipped, failed = sync.sync_all(state=self._state)
        if downloaded or failed:
            self.log(f"Sync: {downloaded} new, {skipped} already downloaded, {failed} failed")

    def _ask_overwrite(self, target: str) -> str:
        """Interactive overwrite prompt (skips automatically when not a TTY)."""
        if self._current_policy != POLICY_ASK:
            return self._current_policy
        if not sys.stdin or not sys.stdin.isatty():
            self.log(f"{target} exists; skipping (non-interactive; use --always-overwrite)")
            return POLICY_SKIP
        try:
            answer = (
                input(f"{target} exists. Overwrite? [y]es/[n]o/[a]ll/[s]kip all: ").strip().lower()
            )
        except EOFError:
            return POLICY_SKIP
        if answer in ("a", "all"):
            self._current_policy = POLICY_OVERWRITE
            return POLICY_OVERWRITE
        if answer in ("s", "skip"):
            self._current_policy = POLICY_SKIP
            return POLICY_SKIP
        return POLICY_OVERWRITE if answer in ("y", "yes") else POLICY_SKIP

    def _maybe_delete(self, client: CameraClient, saved: list) -> None:
        if not self.delete_after or not saved:
            return
        deleted = 0
        for obj in list(saved):
            try:
                client.delete_object(obj.handle)
                deleted += 1
            except (CameraError, TransportError) as exc:
                self.log(f"Could not delete {obj.filename}: {exc}")
        saved.clear()
        if deleted:
            self.log(f"Deleted {deleted} file(s) from the camera")

    def _connect(self, address: str, port: int) -> CameraClient | None:
        for attempt in range(1, CONNECT_ATTEMPTS + 1):
            if self._stop.is_set():
                return None
            client = CameraClient(
                host=address,
                port=port,
                client_name=self.config.client_name,
                client_guid=bytes.fromhex(self.config.client_guid),
                connect_timeout=CONNECT_TIMEOUT,
            )
            try:
                client.open()
                return client
            except (CameraError, TransportError):
                try:
                    client.disconnect()
                except Exception:  # pragma: no cover - defensive
                    pass
                if attempt % 8 == 1:
                    self.log(f"Waiting for camera… ({attempt}/{CONNECT_ATTEMPTS})")
                time.sleep(CONNECT_RETRY_DELAY)
        return None

    # -- helpers -----------------------------------------------------------

    def _ensure_identity(self) -> None:
        if not self.config.client_guid:
            self.config.client_guid = random_guid().hex()
            self.config.save()
        if not self.config.client_name:
            self.config.client_name = "EOS Utility for Linux"

    def _install_signal_handlers(self) -> None:
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, self._on_signal)
            except (ValueError, OSError):  # pragma: no cover - non-main thread
                pass

    def _on_signal(self, _signum, _frame) -> None:
        self.log("Stopping…")
        self._stop.set()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="canon-eos-daemon",
        description="Headless Canon EOS auto-sync daemon",
    )
    parser.add_argument("--config", help="path to config.toml")
    parser.add_argument("--host", help="connect to a fixed host[:port] instead of mDNS discovery")
    parser.add_argument("--once", action="store_true", help="sync once and exit")
    parser.add_argument("--interval", type=float, help="seconds between polls while connected")
    parser.add_argument("--download-dir", help="override the download directory")
    parser.add_argument("--template", help="override the file naming template")

    overwrite = parser.add_mutually_exclusive_group()
    overwrite.add_argument(
        "--always-overwrite",
        action="store_true",
        help="replace existing files without prompting",
    )
    overwrite.add_argument(
        "--no-overwrite",
        action="store_true",
        help="skip files that already exist without prompting",
    )

    delete = parser.add_mutually_exclusive_group()
    delete.add_argument(
        "--delete-after-download",
        action="store_true",
        help="delete files from the camera after they are downloaded",
    )
    delete.add_argument(
        "--no-delete",
        action="store_true",
        help="never delete files from the camera (default)",
    )
    args = parser.parse_args(argv)

    config = AppConfig.load(args.config) if args.config else AppConfig.load()
    if args.download_dir:
        config.download_directory = args.download_dir
    if args.template:
        config.filename_template = args.template

    overwrite_policy = None
    if args.always_overwrite:
        overwrite_policy = POLICY_OVERWRITE
    elif args.no_overwrite:
        overwrite_policy = POLICY_SKIP

    delete_after = None
    if args.delete_after_download:
        delete_after = True
    elif args.no_delete:
        delete_after = False

    daemon = CameraDaemon(
        config,
        host=args.host,
        once=args.once,
        interval=args.interval,
        overwrite_policy=overwrite_policy,
        delete_after=delete_after,
    )
    return daemon.run()


if __name__ == "__main__":
    raise SystemExit(main())
