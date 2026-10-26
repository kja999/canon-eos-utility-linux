"""Background worker owning the :class:`CameraClient`.

All blocking network work happens on a dedicated thread.  The GUI talks to the
worker by posting callables onto a queue and receives updates through Qt
signals (delivered to the GUI thread via queued connections).
"""

from __future__ import annotations

import os
import queue
import threading
import time
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, Signal

from ..config import AppConfig
from ..constants import PTPIP_PORT, LiveViewOutput, ResponseCode
from ..exceptions import CameraError, NotConnectedError
from ..models import (
    AllowedValuesChanged,
    CameraEvent,
    CameraInfo,
    CameraObject,
    ObjectAdded,
    PropertyChanged,
)
from ..naming import DEFAULT_TEMPLATE
from ..protocol import CameraClient, TransportError
from ..sync import (
    POLICY_ASK,
    POLICY_OVERWRITE,
    POLICY_SKIP,
    early_skip,
    finalize_download,
    partial_path,
)

EVENT_POLL_INTERVAL = 0.2
LIVE_VIEW_POLL_INTERVAL = 0.2
CONNECT_ATTEMPTS = 40
CONNECT_RETRY_DELAY = 0.5
CONNECT_TIMEOUT = 2.0

#: How long to wait for the GUI to answer an "overwrite?" prompt.
CONFLICT_PROMPT_TIMEOUT = 600.0

#: Download tuning.
DOWNLOAD_CHUNK = 1 << 20  # 1 MiB GetPartialObject chunks
DOWNLOAD_MAX_RECOVER = 20

#: After a capture, wait for the new file to appear on the card.
CAPTURE_WAIT_SECONDS = 15.0
CAPTURE_POLL_INTERVAL = 0.5


@dataclass
class FileConflict:
    """Carries an "overwrite?" question from the worker to the GUI thread."""

    target: str
    overwrite: bool = False
    apply_to_all: bool = False
    event: threading.Event = field(default_factory=threading.Event)


def _split_host_port(value: str) -> tuple[str, int]:
    """Accept ``host`` or ``host:port`` and return ``(host, port)``."""
    value = value.strip()
    if value.count(":") == 1:
        host, _, port_text = value.partition(":")
        if port_text.isdigit():
            return host, int(port_text)
    return value, PTPIP_PORT


class CameraWorker(QObject):
    connected = Signal(object)  # CameraInfo
    deviceInfo = Signal(object)  # DeviceInfo
    disconnected = Signal()
    connectionFailed = Signal(str)
    errorOccurred = Signal(str)
    statusChanged = Signal(str)

    # NOTE: payloads that carry 32-bit object handles or Python objects use
    # ``object`` rather than ``int``/``dict``/``list``.  PySide maps a bare
    # ``int`` to a *signed* C++ int and ``dict`` to a QVariantMap, both of
    # which overflow / reject Canon's unsigned handles and int-keyed dicts.
    propertiesChanged = Signal(object)  # {property_code: value}
    allowedValuesChanged = Signal(object)  # {property_code: [values]}

    objectsLoaded = Signal(object)  # [CameraObject]
    thumbnailReady = Signal(object, bytes)
    objectAdded = Signal(object)

    downloadProgress = Signal(int, int, str)
    downloadBytes = Signal(object, object)
    downloadFinished = Signal(int)
    #: Emitted (worker thread) when a batch of downloads finished; the payload
    #: is the list of verified :class:`CameraObject`s that were saved.
    downloadsCompleted = Signal(object)
    #: Emitted (worker thread) to ask the GUI whether to overwrite ``FileConflict.target``.
    fileExists = Signal(object)
    #: Emitted after files were deleted from the camera.
    filesDeleted = Signal(int)

    liveViewFrame = Signal(bytes)
    liveViewTouchAf = Signal(int, int, int, int)
    captureCompleted = Signal()

    def __init__(self, client_name: str, client_guid: bytes) -> None:
        super().__init__()
        self._client_name = client_name
        self._client_guid = client_guid

        self.client: CameraClient | None = None
        self.known_properties: dict[int, int] = {}
        self._address: str | None = None
        self._port: int = PTPIP_PORT
        self._connected_once = False

        #: Downloads still to finish, as ``(CameraObject, directory)``.  Kept
        #: across reconnects so an interrupted transfer resumes automatically.
        self._pending_downloads: list[tuple[CameraObject, str]] = []
        self._download_total = 0
        self.config = AppConfig()
        self._camera_context: dict = {}
        self._overwrite_policy = POLICY_ASK
        self._batch_objects: list[CameraObject] = []

        self._commands: queue.Queue = queue.Queue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._live_view_enabled = False
        self._next_event_poll = 0.0
        self._next_live_view_poll = 0.0

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="camera-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._commands.put(None)
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None

    def set_identity(self, client_name: str, client_guid: bytes) -> None:
        self._client_name = client_name
        self._client_guid = client_guid

    def set_download_config(self, filename_template: str) -> None:
        self.config.filename_template = filename_template or DEFAULT_TEMPLATE

    def set_config(self, config: AppConfig) -> None:
        self.config = config
        self._overwrite_policy = POLICY_OVERWRITE if config.always_overwrite else POLICY_ASK

    # -- public API (called from the GUI thread) ---------------------------

    def connect_camera(self, host: str) -> None:
        self._submit(lambda: self._do_connect(host))

    def disconnect_camera(self) -> None:
        self._submit(self._do_disconnect)

    def refresh_gallery(self) -> None:
        self._submit(self._do_load_gallery)

    def set_property(self, code: int, value: int) -> None:
        self._submit(lambda: self._do_set_property(code, value))

    def capture(self) -> None:
        self._submit(self._do_capture)

    def autofocus(self) -> None:
        self._submit(self._do_autofocus)

    def set_live_view(self, enabled: bool) -> None:
        self._submit(lambda: self._do_set_live_view(enabled))

    def touch_af(self, x: int, y: int) -> None:
        self._submit(lambda: self._do_touch_af(x, y))

    def download_objects(self, handles: list[int], directory: str) -> None:
        self._submit(lambda: self._do_download(handles, directory))

    def delete_object(self, handle: int) -> None:
        self._submit(lambda: self._do_delete(handle))

    def delete_objects(self, handles: list[int]) -> None:
        self._submit(lambda: self._do_delete_objects(list(handles)))

    # -- internals ---------------------------------------------------------

    def _submit(self, func) -> None:
        self._commands.put(func)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                try:
                    command = self._commands.get(timeout=0.05)
                except queue.Empty:
                    command = None

                if command is not None:
                    try:
                        command()
                    except CameraError as exc:
                        self.errorOccurred.emit(str(exc))
                    except Exception as exc:  # pragma: no cover - defensive
                        self.errorOccurred.emit(f"{type(exc).__name__}: {exc}")
                    continue

                if self.client is not None and self.client.connected:
                    try:
                        self._maybe_poll()
                    except (TransportError, NotConnectedError) as exc:
                        self._handle_connection_loss(exc)
            except Exception as exc:  # pragma: no cover - keep the worker alive
                self.errorOccurred.emit(f"worker error: {exc}")

    def _handle_connection_loss(self, exc: Exception | None = None) -> None:
        """Drop a dead session and tell the GUI so it can reconnect."""
        if self.client is None and not self._connected_once:
            return
        if self.client is not None:
            try:
                self.client.disconnect()
            except Exception:  # pragma: no cover - defensive
                pass
        self.client = None
        self._connected_once = False
        self._live_view_enabled = False
        reason = f" ({exc})" if exc else ""
        if self._pending_downloads:
            self.statusChanged.emit(
                "Connection lost — will resume downloads when the camera returns" + reason
            )
        else:
            self.statusChanged.emit("Connection lost — waiting for the camera" + reason)
        self.disconnected.emit()

    def _maybe_poll(self) -> None:
        now = time.monotonic()
        if now >= self._next_event_poll:
            self._next_event_poll = now + EVENT_POLL_INTERVAL
            self._do_poll_events()
        if self._live_view_enabled and now >= self._next_live_view_poll:
            self._next_live_view_poll = now + LIVE_VIEW_POLL_INTERVAL
            self._do_poll_live_view()

    # -- command implementations ------------------------------------------

    def _do_connect(self, host: str) -> None:
        address, port = _split_host_port(host)
        self._address = address
        self._port = port
        last_error: Exception | None = None

        # Canon bodies only listen briefly while the camera shows
        # "pairing/connection in progress".  Poll quickly and with a short
        # connect timeout so we can slip into that window instead of sleeping
        # through it.
        client = CameraClient(
            host=address,
            port=port,
            client_name=self._client_name,
            client_guid=self._client_guid,
            connect_timeout=CONNECT_TIMEOUT,
        )
        self.statusChanged.emit(f"Waiting for {address}:{port} to accept a connection…")

        for attempt in range(1, CONNECT_ATTEMPTS + 1):
            if self._stop.is_set():
                return
            try:
                info: CameraInfo = client.open()
            except (CameraError, TransportError) as exc:
                last_error = exc
                try:
                    client.disconnect()
                except Exception:  # pragma: no cover - defensive
                    pass
                if attempt % 8 == 1:
                    self.statusChanged.emit(f"Waiting for camera… ({attempt}/{CONNECT_ATTEMPTS})")
                time.sleep(CONNECT_RETRY_DELAY)
                continue

            self.client = client
            self.known_properties.clear()
            self._connected_once = True
            self.connected.emit(info)
            self.statusChanged.emit(f"Connected to {info.display_name}")
            try:
                device = client.get_device_info()
                self._camera_context = {
                    "model": device.model or info.name,
                    "manufacturer": device.manufacturer,
                    "serial": device.serial_number,
                    "firmware": device.device_version,
                    "name": info.name,
                }
                self.deviceInfo.emit(device)
            except CameraError as exc:
                self._camera_context = {"model": info.name, "name": info.name}
                self.errorOccurred.emit(str(exc))

            self._do_load_gallery()

            if self._pending_downloads:
                self.statusChanged.emit(
                    f"Resuming {len(self._pending_downloads)} pending download(s)…"
                )
                self._run_download_queue()
            return

        self.connectionFailed.emit(f"Could not connect to {address}:{port}\n\n{last_error}")
        self.statusChanged.emit("Connection failed")

    def _do_disconnect(self) -> None:
        self._live_view_enabled = False
        self._connected_once = False
        self._pending_downloads.clear()
        if self.client is not None:
            try:
                self.client.disconnect()
            except Exception:  # pragma: no cover - defensive
                pass
        self.client = None
        self.disconnected.emit()
        self.statusChanged.emit("Disconnected")

    def _do_load_gallery(self) -> None:
        if self.client is None:
            return
        self.statusChanged.emit("Reading camera contents…")
        objects = self.client.list_objects()
        media = [obj for obj in objects if obj.is_image or obj.is_movie]
        self.objectsLoaded.emit(media)

        loaded = 0
        for obj in media:
            if not obj.is_image:
                continue
            try:
                thumbnail = self.client.get_thumbnail(obj.handle)
            except Exception:  # noqa: BLE001 - one bad object must not stop the rest
                continue
            if thumbnail:
                self.thumbnailReady.emit(obj.handle, thumbnail)
                loaded += 1
        self.statusChanged.emit(f"{len(media)} items on camera ({loaded} previews)")

    def _do_set_property(self, code: int, value: int) -> None:
        if self.client is None:
            return
        self.client.set_property(code, value)

    def _do_capture(self) -> None:
        if self.client is None:
            return
        self.statusChanged.emit("Capturing…")
        before = self._object_handles()
        self.client.capture_image()
        self.statusChanged.emit("Capture complete — waiting for the file…")
        self.captureCompleted.emit()

        # The camera writes the new file to the card asynchronously, so poll
        # until a new object shows up (or give up after a few seconds).
        deadline = time.monotonic() + CAPTURE_WAIT_SECONDS
        while not self._stop.is_set() and time.monotonic() < deadline:
            time.sleep(CAPTURE_POLL_INTERVAL)
            handles = self._object_handles()
            if handles - before:
                break

        self._do_load_gallery()

    def _object_handles(self) -> set[int]:
        if self.client is None:
            return set()
        try:
            return {obj.handle for obj in self.client.list_objects()}
        except (CameraError, TransportError):
            return set()

    def _do_autofocus(self) -> None:
        if self.client is None:
            return
        self.statusChanged.emit("Autofocus…")
        self.client.start_autofocus()
        time.sleep(0.8)
        self.client.stop_autofocus()
        self.statusChanged.emit("Autofocus done")

    def _do_set_live_view(self, enabled: bool) -> None:
        if self.client is None:
            return
        if enabled:
            try:
                self.client.enable_live_view()
            except CameraError as exc:
                # Not fatal: some bodies ignore the output property yet still
                # stream frames, so keep polling anyway.
                self.errorOccurred.emit(f"Live view output: {exc}")
            self._live_view_enabled = True
        else:
            try:
                self.client.set_live_view_output(LiveViewOutput.NONE, busy_retries=3)
            except CameraError:
                pass
            self._live_view_enabled = False
        self._next_live_view_poll = 0.0
        self.statusChanged.emit("Live view on" if enabled else "Live view off")

    def _do_touch_af(self, x: int, y: int) -> None:
        if self.client is None:
            return
        self.client.set_touch_af_position(x, y)

    def _do_poll_events(self) -> None:
        if self.client is None:
            return
        events: list[CameraEvent] = self.client.poll_events()
        changed: dict[int, int] = {}
        allowed: dict[int, list[int]] = {}
        for event in events:
            if isinstance(event, PropertyChanged):
                if self.known_properties.get(event.code) != event.value:
                    self.known_properties[event.code] = event.value
                    changed[event.code] = event.value
            elif isinstance(event, AllowedValuesChanged):
                allowed[event.code] = event.values
            elif isinstance(event, ObjectAdded):
                self.objectAdded.emit(event.handle)

        if changed:
            self.propertiesChanged.emit(changed)
        if allowed:
            self.allowedValuesChanged.emit(allowed)

    def _do_poll_live_view(self) -> None:
        if self.client is None:
            return
        try:
            frame = self.client.get_live_view_image(busy_retries=2)
        except CameraError:
            return
        if frame.jpeg:
            self.liveViewFrame.emit(frame.jpeg)
        if frame.touch_af is not None:
            af = frame.touch_af
            self.liveViewTouchAf.emit(af.x, af.y, af.width, af.height)

    def _do_download(self, handles: list[int], directory: str) -> None:
        if self.client is None or not handles:
            return
        os.makedirs(directory, exist_ok=True)

        items: list[tuple[CameraObject, str]] = []
        for handle in handles:
            try:
                obj = self.client.get_object_info(handle)
            except (CameraError, TransportError) as exc:
                self.errorOccurred.emit(f"Cannot read info for object {handle}: {exc}")
                continue
            items.append((obj, directory))

        if not items:
            return
        self._pending_downloads = items
        self._download_total = len(items)
        self._batch_objects = []
        self._run_download_queue()

    def _run_download_queue(self) -> None:
        """Process pending downloads, resuming each from its ``.part`` file.

        The queue survives a lost connection: if the camera disappears the
        method returns with the queue intact and resumes automatically on the
        next successful connect.
        """
        while self._pending_downloads and not self._stop.is_set():
            obj, directory = self._pending_downloads[0]
            filename = obj.filename or f"IMG_{obj.handle}"
            base, template = self._output_for(obj, directory)

            if self.client is None or not self.client.connected:
                self._pause_downloads()
                return

            # Avoid transferring files we already have locally; the same check
            # runs again at finalize for templates that cannot be predicted.
            if early_skip(
                obj,
                base,
                template,
                self._camera_context,
                self._overwrite_policy,
                self._resolve_conflict,
            ):
                self.statusChanged.emit(f"Skipped {filename} (already exists)")
                self._pending_downloads.pop(0)
                continue

            part = partial_path(base, filename)
            offset = os.path.getsize(part) if os.path.exists(part) else 0
            done = self._download_total - len(self._pending_downloads)
            self.downloadProgress.emit(done, self._download_total, filename)

            if obj.size and offset >= obj.size:
                if self._finalize(obj, base, part, template) is not None:
                    self._batch_objects.append(obj)
                self._pending_downloads.pop(0)
                continue

            if offset:
                self.statusChanged.emit(f"Resuming {filename} from {offset} of {obj.size} bytes…")
            self.downloadBytes.emit(offset, obj.size or offset)

            handle = self._resolve_handle(filename, obj.size) or obj.handle
            if self._download_one(handle, filename, obj.size, part, offset):
                if self._finalize(obj, base, part, template) is not None:
                    self._batch_objects.append(obj)
                self._pending_downloads.pop(0)
            elif self.client is None or not self.client.connected:
                self._pause_downloads()
                return
            else:
                # Genuine failure (not connectivity): drop it to avoid looping.
                self.errorOccurred.emit(f"Download of {filename} failed")
                self._pending_downloads.pop(0)

        if not self._pending_downloads:
            total = self._download_total
            self.downloadFinished.emit(total)
            self._download_total = 0
            if self._batch_objects:
                self.downloadsCompleted.emit(list(self._batch_objects))
                self._batch_objects = []

    def _output_for(self, obj: CameraObject, directory: str) -> tuple[str, str]:
        """Pick the destination directory and template for an object.

        Videos can use their own directory/template when enabled; the type is
        taken from the object (``is_movie``) which the client detected from the
        PTP format code / file extension.
        """
        if obj.is_movie and self.config.use_video_template:
            return (
                self.config.resolved_video_directory(),
                self.config.video_filename_template or self.config.filename_template,
            )
        return directory, self.config.filename_template

    def _pause_downloads(self) -> None:
        remaining = len(self._pending_downloads)
        self.statusChanged.emit(
            f"Downloads paused — {remaining} file(s) will resume when the camera returns"
        )

    def _download_one(self, handle: int, filename: str, size: int, part: str, offset: int) -> bool:
        """Download one object to ``part``, resuming at ``offset``.

        Transfers are chunked with ``GetPartialObject`` so an interrupted
        transfer can continue from the last byte received.  If the connection
        drops we reconnect and re-resolve the object handle by filename, since
        Canon reassigns handles on every session.
        """
        if not size:
            return self._download_full(handle, part)

        recoveries = 0
        with open(part, "ab") as handle_file:
            while offset < size:
                if self._stop.is_set():
                    return False
                try:
                    chunk = self.client.get_partial_object(handle, offset, DOWNLOAD_CHUNK)
                except CameraError as exc:
                    if offset == 0 and exc.response_code in (
                        ResponseCode.OPERATION_NOT_SUPPORTED,
                        ResponseCode.PARAMETER_NOT_SUPPORTED,
                        ResponseCode.INVALID_PARAMETER,
                    ):
                        return self._download_full(handle, part)
                    if not self._recover(filename, exc, recoveries):
                        return False
                    recoveries += 1
                    handle = self._resolve_handle(filename, size) or handle
                    continue
                except TransportError as exc:
                    if not self._recover(filename, exc, recoveries):
                        return False
                    recoveries += 1
                    handle = self._resolve_handle(filename, size) or handle
                    continue

                if not chunk:
                    self.errorOccurred.emit(
                        f"{filename}: camera returned no data at offset {offset}"
                    )
                    return False

                handle_file.write(chunk)
                handle_file.flush()
                offset += len(chunk)
                self.downloadBytes.emit(offset, size)

        return offset >= size

    def _download_full(self, handle: int, part: str) -> bool:
        try:
            data = self.client.get_object(handle)
        except (CameraError, TransportError) as exc:
            self.errorOccurred.emit(f"Download failed: {exc}")
            return False
        with open(part, "wb") as handle_file:
            handle_file.write(data)
        self.downloadBytes.emit(len(data), len(data))
        return True

    def _finalize(self, obj: CameraObject, directory: str, part: str, template: str) -> str | None:
        """Move a completed ``.part`` file into place and verify its size."""
        target = finalize_download(
            obj,
            directory,
            part,
            template,
            self._camera_context,
            set_times=self.config.set_file_times,
            policy=self._overwrite_policy,
            ask=self._resolve_conflict,
        )
        if target is None:
            self.statusChanged.emit(f"Skipped {obj.filename} (already exists)")
            return None
        if obj.size and os.path.getsize(target) != obj.size:
            self.errorOccurred.emit(f"{obj.filename}: size mismatch after download, not verified")
            return None
        self.statusChanged.emit(f"Saved {os.path.relpath(target, directory)}")
        return target

    def _resolve_conflict(self, target: str) -> str:
        """Ask the GUI whether to overwrite an existing file."""
        if self._overwrite_policy != POLICY_ASK:
            return self._overwrite_policy
        conflict = FileConflict(target=target)
        self.fileExists.emit(conflict)
        if not conflict.event.wait(timeout=CONFLICT_PROMPT_TIMEOUT):
            return POLICY_SKIP
        decision = POLICY_OVERWRITE if conflict.overwrite else POLICY_SKIP
        if conflict.apply_to_all:
            self._overwrite_policy = decision
        return decision

    def _recover(self, filename: str, exc: Exception, recoveries: int) -> bool:
        if recoveries >= DOWNLOAD_MAX_RECOVER:
            self.errorOccurred.emit(f"Download of {filename} failed: {exc}")
            self._handle_connection_loss(exc)
            return False
        self.statusChanged.emit(f"Transfer of {filename} interrupted, reconnecting to resume…")
        if not self._recover_connection():
            self._handle_connection_loss(exc)
            return False
        return True

    def _recover_connection(self) -> bool:
        if self._address is None:
            return False
        try:
            if self.client is not None:
                self.client.disconnect()
        except Exception:  # pragma: no cover - defensive
            pass
        self.client = None

        for _attempt in range(1, CONNECT_ATTEMPTS + 1):
            if self._stop.is_set():
                return False
            client = CameraClient(
                host=self._address,
                port=self._port,
                client_name=self._client_name,
                client_guid=self._client_guid,
                connect_timeout=CONNECT_TIMEOUT,
            )
            try:
                client.open()
            except (CameraError, TransportError):
                try:
                    client.disconnect()
                except Exception:  # pragma: no cover - defensive
                    pass
                time.sleep(CONNECT_RETRY_DELAY)
                continue
            self.client = client
            self._connected_once = True
            self.known_properties.clear()
            self.connected.emit(client.info)
            return True
        return False

    def _resolve_handle(self, filename: str, size: int) -> int | None:
        if self.client is None:
            return None
        try:
            objects = self.client.list_objects()
        except (CameraError, TransportError):
            return None
        for obj in objects:
            if obj.filename == filename and (not size or obj.size == size):
                return obj.handle
        return None

    def _do_delete(self, handle: int) -> None:
        if self.client is None:
            return
        self.client.delete_object(handle)
        self._do_load_gallery()

    def _do_delete_objects(self, handles: list[int]) -> None:
        if self.client is None or not handles:
            return
        deleted = 0
        for handle in handles:
            try:
                self.client.delete_object(handle)
                deleted += 1
            except (CameraError, TransportError) as exc:
                self.errorOccurred.emit(f"Could not delete object {handle}: {exc}")
        self.statusChanged.emit(f"Deleted {deleted} file(s) from the camera")
        self.filesDeleted.emit(deleted)
        self._do_load_gallery()
