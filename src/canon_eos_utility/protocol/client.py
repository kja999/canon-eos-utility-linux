"""High level, synchronous Canon EOS camera client built on PTP/IP.

The client owns two sockets (command + event channels), performs the pairing /
session initialisation handshake and exposes friendly methods for browsing and
downloading objects, reading / writing properties, capturing images and
streaming Live View frames.
"""

from __future__ import annotations

import threading
import time
import uuid

from ..constants import (
    PTPIP_PORT,
    CaptureDestination,
    CapturePhase,
    DataPhase,
    EventMode,
    LiveViewOutput,
    OperationCode,
    PropertyCode,
    RemoteMode,
    ResponseCode,
)
from ..exceptions import CameraError, NotConnectedError
from ..models import (
    CameraEvent,
    CameraInfo,
    CameraObject,
    DeviceInfo,
    StorageInfo,
)
from .codec import (
    LiveViewFrame,
    parse_device_info,
    parse_event_data,
    parse_live_view,
    parse_num_objects,
    parse_object_handles,
    parse_object_info,
    parse_storage_ids,
    parse_storage_info,
)
from .packets import (
    DataPacket,
    EndData,
    InitCommandAck,
    InitCommandRequest,
    InitEventAck,
    InitEventRequest,
    OperationResponse,
    StartData,
)
from .transport import Transport, TransportError

#: The EOS Utility sends its polling command five times a second.
DEFAULT_EVENT_POLL_INTERVAL = 0.2


def random_guid() -> bytes:
    return uuid.uuid4().bytes


class CameraClient:
    """Synchronous PTP/IP client for a single Canon EOS camera."""

    def __init__(
        self,
        host: str,
        port: int = PTPIP_PORT,
        client_name: str | None = None,
        client_guid: bytes | None = None,
        timeout: float = 10.0,
        connect_timeout: float = 5.0,
    ) -> None:
        self.host = host
        self.port = port
        self.client_name = (client_name or "EOS Utility for Linux")[:32]
        self.client_guid = client_guid or random_guid()
        self.timeout = timeout
        self.connect_timeout = connect_timeout

        self.command: Transport | None = None
        self.event: Transport | None = None
        self.info: CameraInfo | None = None
        self.device_info: DeviceInfo | None = None

        self._transaction_id = 0
        self._lock = threading.RLock()

    # -- lifecycle ---------------------------------------------------------

    @property
    def connected(self) -> bool:
        return self.command is not None and self.info is not None

    def __enter__(self) -> CameraClient:
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.disconnect()

    def open(self) -> CameraInfo:
        """Pair/connect, then initialise the PTP session.

        The camera must be in the "Remote control (EOS Utility)" Wi-Fi screen;
        on a first connection it will ask the user to confirm the pairing.
        """
        with self._lock:
            try:
                self.command = Transport(
                    self.host,
                    self.port,
                    timeout=self.timeout,
                    connect_timeout=self.connect_timeout,
                )
                response = self.command.send_recv(
                    InitCommandRequest(guid=self.client_guid, name=self.client_name)
                )
                if not isinstance(response, InitCommandAck):
                    raise CameraError(f"unexpected response to init command request: {response!r}")
                connection_number = response.connection_number
                camera_guid = response.guid
                camera_name = response.name

                self.event = Transport(
                    self.host,
                    self.port,
                    timeout=self.timeout,
                    connect_timeout=self.connect_timeout,
                )
                ack = self.event.send_recv(InitEventRequest(connection_number=connection_number))
                if not isinstance(ack, InitEventAck):
                    raise CameraError(f"unexpected response to init event request: {ack!r}")

                self.info = CameraInfo(
                    guid=camera_guid,
                    name=camera_name,
                    connection_number=connection_number,
                    version=response.version,
                    address=self.host,
                )

                self._open_session()
                self._set_remote_mode(RemoteMode.ENABLED)
                self._set_event_mode(EventMode.ENABLED)
                # Some bodies (e.g. the EOS R5) reject 0xD11C with DEVICE_BUSY;
                # that is not fatal, the camera still stores to card by default.
                try:
                    self.set_capture_destination(CaptureDestination.STORAGE2)
                except CameraError:
                    pass
                return self.info
            except Exception:
                self.disconnect()
                raise

    def disconnect(self) -> None:
        with self._lock:
            if self.command is not None:
                try:
                    self._transact(OperationCode.CLOSE_SESSION)
                except (CameraError, TransportError):
                    pass
            for transport in (self.event, self.command):
                if transport is not None:
                    try:
                        transport.close()
                    except OSError:  # pragma: no cover
                        pass
            self.command = None
            self.event = None
            self.info = None

    # -- PTP session setup -------------------------------------------------

    def _open_session(self, session_id: int = 1) -> OperationResponse:
        return self._transact(OperationCode.OPEN_SESSION, params=[session_id], busy_retries=3)

    def _set_remote_mode(self, mode: RemoteMode) -> OperationResponse:
        return self._transact(OperationCode.SET_REMOTE_MODE, params=[int(mode)], busy_retries=3)

    def _set_event_mode(self, mode: EventMode) -> OperationResponse:
        return self._transact(OperationCode.SET_EVENT_MODE, params=[int(mode)], busy_retries=3)

    def set_capture_destination(self, destination: CaptureDestination) -> None:
        self.set_prop_value(PropertyCode.CAPTURE_DESTINATION, int(destination))

    # -- generic transaction ----------------------------------------------

    def _next_transaction_id(self) -> int:
        self._transaction_id = (self._transaction_id + 1) & 0xFFFFFFFF
        return self._transaction_id

    def _transact(
        self,
        operation_code: int,
        params: list[int] | None = None,
        data: bytes | None = None,
        busy_retries: int = 0,
    ) -> OperationResponse:
        if self.command is None:
            raise NotConnectedError("camera is not connected")

        from .packets import OperationRequest

        with self._lock:
            for attempt in range(busy_retries + 1):
                transaction_id = self._next_transaction_id()
                data_phase = DataPhase.WITH_DATA if data is not None else DataPhase.NO_DATA
                request = OperationRequest(
                    data_phase=int(data_phase),
                    operation_code=int(operation_code),
                    transaction_id=transaction_id,
                    params=list(params or []),
                )
                self.command.send(request)

                if data is not None:
                    self.command.send(StartData(transaction_id, len(data)))
                    self.command.send(EndData(transaction_id, data))

                try:
                    return self._receive_response(operation_code, transaction_id)
                except CameraError as exc:
                    if exc.response_code == ResponseCode.DEVICE_BUSY and attempt < busy_retries:
                        time.sleep(0.3)
                        continue
                    raise

        raise CameraError(f"{_operation_name(operation_code)} failed")  # pragma: no cover

    def _receive_response(self, operation_code: int, transaction_id: int) -> OperationResponse:
        assert self.command is not None
        collected = bytearray()
        while True:
            packet = self.command.recv()
            if isinstance(packet, StartData):
                collected.clear()
                continue
            if isinstance(packet, DataPacket):
                collected.extend(packet.data)
                continue
            if isinstance(packet, EndData):
                collected.extend(packet.data)
                continue
            if isinstance(packet, OperationResponse):
                packet.data = bytes(collected)
                if packet.response_code != ResponseCode.OK:
                    raise CameraError.from_response(
                        packet.response_code, _operation_name(operation_code)
                    )
                return packet
            # Ignore stray event packets delivered on the command channel.

    # -- device / storage / object browsing -------------------------------

    def get_device_info(self) -> DeviceInfo:
        response = self._transact(OperationCode.GET_DEVICE_INFO)
        info = parse_device_info(response.data)
        self.device_info = info
        if self.info is not None:
            self.info.manufacturer = info.manufacturer
            self.info.model = info.model
            self.info.device_version = info.device_version
            self.info.serial_number = info.serial_number
        return info

    def get_storage_ids(self) -> list[int]:
        response = self._transact(OperationCode.GET_STORAGE_IDS)
        return parse_storage_ids(response.data)

    def get_storage_info(self, storage_id: int) -> StorageInfo:
        response = self._transact(OperationCode.GET_STORAGE_INFO, params=[storage_id])
        info = parse_storage_info(response.data)
        info.storage_id = storage_id
        return info

    def get_num_objects(self) -> int:
        response = self._transact(OperationCode.GET_NUM_OBJECTS)
        return parse_num_objects(response.data)

    def get_object_handles(
        self,
        storage_id: int = 0xFFFFFFFF,
        format_code: int = 0x00000000,
        parent_object: int = 0x00000000,
    ) -> list[int]:
        """Return object handles for a storage.

        Canon bodies (notably the EOS R series) only enumerate objects when a
        concrete storage id is supplied with ``formatCode = 0``; the generic
        ``0xFFFFFFFF`` wildcard returns an empty list.
        """
        response = self._transact(
            OperationCode.GET_OBJECT_HANDLES,
            params=[storage_id, format_code, parent_object],
        )
        return parse_object_handles(response.data)

    def get_object_info(self, handle: int) -> CameraObject:
        response = self._transact(OperationCode.GET_OBJECT_INFO, params=[handle])
        obj = parse_object_info(response.data)
        obj.handle = handle
        return obj

    def list_objects(self) -> list[CameraObject]:
        """Return metadata for every object on the camera.

        All storages are iterated explicitly because Canon cameras do not honour
        the ``0xFFFFFFFF`` storage wildcard in ``GetObjectHandles``.
        """
        handles: list[int] = []
        try:
            storage_ids = self.get_storage_ids()
        except CameraError:
            storage_ids = []

        for storage_id in storage_ids or [0xFFFFFFFF]:
            try:
                handles.extend(self.get_object_handles(storage_id))
            except CameraError:
                continue

        if not handles:
            try:
                handles = self.get_object_handles(0xFFFFFFFF)
            except CameraError:
                handles = []

        objects: list[CameraObject] = []
        for handle in dict.fromkeys(handles):
            try:
                objects.append(self.get_object_info(handle))
            except CameraError:
                continue
        return objects

    def get_object(self, handle: int) -> bytes:
        response = self._transact(OperationCode.GET_OBJECT, params=[handle], busy_retries=3)
        return response.data

    def get_thumbnail(self, handle: int) -> bytes:
        response = self._transact(OperationCode.GET_THUMB, params=[handle], busy_retries=3)
        return response.data

    def get_partial_object(
        self, handle: int, offset: int, length: int, busy_retries: int = 3
    ) -> bytes:
        response = self._transact(
            OperationCode.GET_PARTIAL_OBJECT,
            params=[handle, offset, length],
            busy_retries=busy_retries,
        )
        return response.data

    def iter_object(self, handle: int, size: int = 0, chunk_size: int = 1 << 20):
        """Yield an object's bytes, preferring chunked ``GetPartialObject``.

        Chunking is far more robust than a single multi-hundred-megabyte
        transfer: it reports progress and survives transient ``DEVICE_BUSY``
        responses.  If the camera rejects ``GetPartialObject`` we transparently
        fall back to a full ``GetObject``.
        """
        if size and size > 0:
            offset = 0
            try:
                while offset < size:
                    requested = min(chunk_size, size - offset)
                    chunk = self.get_partial_object(handle, offset, requested)
                    if not chunk:
                        raise CameraError(f"camera returned no data at offset {offset} of {size}")
                    offset += len(chunk)
                    yield chunk
                return
            except CameraError as exc:
                if offset > 0 or exc.response_code not in (
                    ResponseCode.OPERATION_NOT_SUPPORTED,
                    ResponseCode.PARAMETER_NOT_SUPPORTED,
                    ResponseCode.INVALID_PARAMETER,
                ):
                    raise
        data = self.get_object(handle)
        if data:
            yield data

    def download_object(
        self, handle: int, size: int = 0, progress=None, chunk_size: int = 1 << 20
    ) -> bytes:
        """Download a whole object into memory (see :meth:`iter_object`)."""
        data = bytearray()
        for chunk in self.iter_object(handle, size, chunk_size):
            data.extend(chunk)
            if progress is not None:
                progress(len(data), size or len(data))
        return bytes(data)

    def delete_object(self, handle: int) -> None:
        self._transact(OperationCode.DELETE_OBJECT, params=[handle])

    # -- properties -------------------------------------------------------

    def set_prop_value(
        self, prop_code: int, value: int, *, size: int = 4, busy_retries: int = 0
    ) -> None:
        """Set a Canon EOS property (SetDevicePropValueEx, 0x9110).

        The data phase is ``[total_length u32][property_code u32][value]`` where
        ``total_length`` counts itself (12 for a 32-bit value).  Omitting the
        leading length field makes the camera reject the write with DEVICE_BUSY.
        """
        import struct

        value_u32 = int(value) & 0xFFFFFFFF
        payload = struct.pack("<III", 12, int(prop_code), value_u32)
        self._transact(
            OperationCode.SET_PROP_VALUE,
            data=payload,
            busy_retries=busy_retries,
        )

    def set_property(self, prop_code: int, value: int) -> None:
        # Setting a property often returns DEVICE_BUSY briefly after another
        # operation, so retry a little.
        self.set_prop_value(prop_code, value, busy_retries=3)

    def get_device_prop_value(self, prop_code: int) -> bytes:
        response = self._transact(OperationCode.GET_DEVICE_PROP_VALUE, params=[prop_code])
        return response.data

    def get_device_prop_desc(self, prop_code: int) -> bytes:
        response = self._transact(OperationCode.GET_DEVICE_PROP_DESC, params=[prop_code])
        return response.data

    # -- events -----------------------------------------------------------

    def poll_events(self) -> list[CameraEvent]:
        response = self._transact(OperationCode.GET_EVENT_DATA)
        return parse_event_data(response.data)

    # -- capture ----------------------------------------------------------

    def start_image_capture(self, phase: CapturePhase) -> None:
        self._transact(
            OperationCode.START_IMAGE_CAPTURE,
            params=[int(phase), 0x00000000],
        )

    def stop_image_capture(self, phase: CapturePhase) -> None:
        self._transact(OperationCode.STOP_IMAGE_CAPTURE, params=[int(phase)])

    def capture_image(self) -> None:
        """Perform a full autofocus + shutter release sequence."""
        self.start_image_capture(CapturePhase.FOCUS)
        self.start_image_capture(CapturePhase.RELEASE)
        self.stop_image_capture(CapturePhase.RELEASE)
        self.stop_image_capture(CapturePhase.FOCUS)

    def start_autofocus(self) -> None:
        self.start_image_capture(CapturePhase.FOCUS)

    def stop_autofocus(self) -> None:
        self.stop_image_capture(CapturePhase.FOCUS)

    # -- live view --------------------------------------------------------

    def set_live_view_output(self, output: LiveViewOutput, busy_retries: int = 8) -> None:
        self.set_prop_value(PropertyCode.LIVE_VIEW_OUTPUT, int(output), busy_retries=busy_retries)

    def enable_live_view(self) -> bool:
        """Enable live view output, tolerating a busy camera.

        Follows the sequence libgphoto2 uses for EOS bodies: (re)assert remote
        and event mode, turn the electronic viewfinder on (EVFMode), route the
        output to the host, and keep the camera awake.  Returns ``True``; raises
        only if the output property could not be set with any value, so callers
        can still try to poll frames.
        """
        # Re-assert the session modes; harmless if already set.
        for call in (
            lambda: self._set_remote_mode(RemoteMode.ENABLED),
            lambda: self._set_event_mode(EventMode.ENABLED),
        ):
            try:
                call()
            except CameraError:
                pass

        # Switch the EVF on.  This returns DEVICE_BUSY in movie mode, but the
        # live view output can still be enabled, so it is not fatal.
        try:
            self.set_prop_value(PropertyCode.EVF_MODE, 1, size=2, busy_retries=6)
        except CameraError:
            pass

        # Route the live view to the host (3 = cameraAndHost keeps the camera
        # screen on; 2 = host only).
        last_error: CameraError | None = None
        for output in (LiveViewOutput.CAMERA_AND_HOST, LiveViewOutput.HOST):
            try:
                self.set_prop_value(PropertyCode.LIVE_VIEW_OUTPUT, int(output), busy_retries=8)
                last_error = None
                break
            except CameraError as exc:
                last_error = exc

        # Otherwise the camera auto-shuts-down while streaming.
        try:
            self.keep_device_on()
        except CameraError:
            pass

        if last_error is not None:
            raise last_error
        return True

    def keep_device_on(self) -> None:
        """Ask the camera not to sleep while we hold a remote session."""
        self._transact(OperationCode.KEEP_DEVICE_ON)

    def get_live_view_image(self, busy_retries: int = 3) -> LiveViewFrame:
        response = self._transact(
            OperationCode.GET_LIVE_VIEW_IMAGE,
            params=[0x00200000, 0x00000000, 0x00000000],
            busy_retries=busy_retries,
        )
        return parse_live_view(response.data)

    def set_touch_af_position(self, x: int, y: int) -> None:
        self._transact(
            OperationCode.SET_TOUCH_AF_POSITION,
            params=[0x00000003, int(x), int(y)],
        )


_OPERATION_NAMES = {int(code): code.name.lower() for code in OperationCode}


def _operation_name(operation_code: int) -> str:
    return _OPERATION_NAMES.get(int(operation_code), f"operation 0x{operation_code:04X}")
