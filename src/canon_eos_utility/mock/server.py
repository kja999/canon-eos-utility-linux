"""A mock Canon EOS camera speaking enough PTP/IP to exercise the GUI.

The server implements the command/event channel handshake, session
initialisation, object browsing / download, property get/set, the capture
sequence and Live View.  It stores a handful of generated JPEGs so the whole
application can be developed and tested without real hardware.
"""

from __future__ import annotations

import datetime
import socket
import struct
import threading
from collections import deque
from dataclasses import dataclass

from ..constants import (
    APERTURE_VALUES,
    ISO_VALUES,
    SHUTTER_SPEED_VALUES,
    CapturePhase,
    LiveViewOutput,
    ObjectFormat,
    OperationCode,
    PropertyCode,
    ResponseCode,
)
from ..models import (
    AllowedValuesChanged,
    CameraEvent,
    CameraObject,
    DeviceInfo,
    ObjectAdded,
    PropertyChanged,
    StorageInfo,
)
from ..protocol.codec import (
    encode_device_info,
    encode_event_data,
    encode_num_objects,
    encode_object_handles,
    encode_object_info,
    encode_storage_ids,
    encode_storage_info,
)
from ..protocol.packets import (
    ByteWriter,
    DataPacket,
    EndData,
    InitCommandAck,
    InitCommandRequest,
    InitEventAck,
    InitEventRequest,
    OperationRequest,
    Packet,
    StartData,
    encode_packet,
    parse_payload,
    read_frame,
)
from .images import generate_jpeg, generate_thumbnail

DEFAULT_CAMERA_GUID = bytes.fromhex("0000000000000000010060128b7cc240")
MOCK_STORAGE_ID = 0x12345678


@dataclass
class MockImage:
    handle: int
    filename: str
    data: bytes
    thumbnail: bytes
    width: int
    height: int
    fmt: int = int(ObjectFormat.EXIF_JPEG)
    capture_date: str = ""
    protection_status: int = 0

    def as_object(self) -> CameraObject:
        return CameraObject(
            handle=self.handle,
            storage_id=MOCK_STORAGE_ID,
            format=self.fmt,
            size=len(self.data),
            filename=self.filename,
            capture_date=self.capture_date,
            width=self.width,
            height=self.height,
            protection_status=self.protection_status,
        )


class MockCameraState:
    """Mutable state shared by all mock connections."""

    def __init__(self, model: str = "Canon EOS 70D", serial: str = "MOCK0001") -> None:
        self.model = model
        self.manufacturer = "Canon Inc."
        self.serial = serial
        self.device_version = "3.1.0"
        self.lock = threading.RLock()

        self.storage = StorageInfo(
            storage_id=MOCK_STORAGE_ID,
            max_capacity=64 * 1024**3,
            free_space=57 * 1024**3,
            max_objects=9999,
            free_objects=9000,
            description="Memory card",
        )

        self.images: list[MockImage] = []
        self._next_handle = 1
        self.properties: dict[int, int] = {
            int(PropertyCode.APERTURE): 0x30,  # f/5.6
            int(PropertyCode.SHUTTER_SPEED): 0x70,  # 1/125
            int(PropertyCode.ISO): 0x50,  # ISO 200
            int(PropertyCode.WHITE_BALANCE): 0x00,
            int(PropertyCode.CAPTURE_DESTINATION): 0x02,
            int(PropertyCode.LIVE_VIEW_OUTPUT): 0x00,
        }
        self.allowed_values: dict[int, list[int]] = {
            int(PropertyCode.APERTURE): [v for v, _ in APERTURE_VALUES],
            int(PropertyCode.SHUTTER_SPEED): [v for v, _ in SHUTTER_SPEED_VALUES],
            int(PropertyCode.ISO): [v for v, _ in ISO_VALUES],
        }
        self.pending_events: deque[CameraEvent] = deque()
        self._sent_initial_events = False

        self.live_view_output = int(LiveViewOutput.NONE)
        self.touch_af = (0, 0)
        self._live_view_counter = 0

        #: Test hook: when set to a byte offset, the GetPartialObject request for
        #: that offset closes the connection to simulate a mid-transfer drop.
        self.drop_partial_offset: int | None = None

        #: Test hook: delay (seconds) before a captured image becomes visible,
        #: simulating the camera writing the file to the card.
        self.capture_delay_seconds = 0.0

        self.populate_sample_images()

    # -- helpers -----------------------------------------------------------

    def queue_capture(self) -> None:
        """Register a captured image, optionally after a delay."""
        delay = self.capture_delay_seconds
        if delay and delay > 0:
            threading.Timer(delay, self._deferred_capture).start()
        else:
            self.add_captured_image()

    def _deferred_capture(self) -> None:
        with self.lock:
            self.add_captured_image()

    def populate_sample_images(self, count: int = 4) -> None:
        widths = [(1600, 1067), (1600, 1067), (1067, 1600), (1600, 1067)]
        for index in range(count):
            width, height = widths[index % len(widths)]
            handle = self._next_handle
            self._next_handle += 1
            label = f"IMG_{index + 1:04d}"
            jpeg = generate_jpeg(width, height, index, label)
            self.images.append(
                MockImage(
                    handle=handle,
                    filename=f"{label}.JPG",
                    data=jpeg,
                    thumbnail=generate_thumbnail(jpeg),
                    width=width,
                    height=height,
                    capture_date=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                )
            )

    def add_captured_image(self) -> MockImage:
        handle = self._next_handle
        self._next_handle += 1
        label = f"IMG_{len(self.images) + 1:04d}"
        jpeg = generate_jpeg(1600, 1067, len(self.images), label)
        image = MockImage(
            handle=handle,
            filename=f"{label}.JPG",
            data=jpeg,
            thumbnail=generate_thumbnail(jpeg),
            width=1600,
            height=1067,
            capture_date=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
        self.images.append(image)
        self.pending_events.append(ObjectAdded(handle=handle))
        return image

    def find_image(self, handle: int) -> MockImage | None:
        return next((image for image in self.images if image.handle == handle), None)

    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            standard_version=100,
            vendor_extension_id=0x00000006,
            vendor_extension_version=100,
            vendor_extension_description="Canon EOS",
            functional_mode=0,
            operations=[
                int(op)
                for op in (
                    OperationCode.GET_DEVICE_INFO,
                    OperationCode.OPEN_SESSION,
                    OperationCode.CLOSE_SESSION,
                    OperationCode.GET_STORAGE_IDS,
                    OperationCode.GET_STORAGE_INFO,
                    OperationCode.GET_OBJECT_HANDLES,
                    OperationCode.GET_OBJECT_INFO,
                    OperationCode.GET_OBJECT,
                    OperationCode.GET_THUMB,
                    OperationCode.GET_PARTIAL_OBJECT,
                    OperationCode.DELETE_OBJECT,
                    OperationCode.SET_PROP_VALUE,
                    OperationCode.SET_REMOTE_MODE,
                    OperationCode.SET_EVENT_MODE,
                    OperationCode.GET_EVENT_DATA,
                    OperationCode.START_IMAGE_CAPTURE,
                    OperationCode.STOP_IMAGE_CAPTURE,
                    OperationCode.GET_LIVE_VIEW_IMAGE,
                    OperationCode.SET_TOUCH_AF_POSITION,
                )
            ],
            image_formats=[int(ObjectFormat.EXIF_JPEG)],
            manufacturer=self.manufacturer,
            model=self.model,
            device_version=self.device_version,
            serial_number=self.serial,
        )

    def drain_events(self) -> list[CameraEvent]:
        with self.lock:
            events: list[CameraEvent] = []
            if not self._sent_initial_events:
                self._sent_initial_events = True
                for code, value in self.properties.items():
                    events.append(PropertyChanged(code=code, value=value))
                for code, values in self.allowed_values.items():
                    events.append(AllowedValuesChanged(code=code, values=list(values)))
            while self.pending_events:
                events.append(self.pending_events.popleft())
            return events


class _ConnectionHandler(threading.Thread):
    def __init__(self, server: MockCameraServer, conn: socket.socket, addr) -> None:
        super().__init__(daemon=True)
        self.server = server
        self.state = server.state
        self.conn = conn
        self.addr = addr
        self._buffer = bytearray()
        self._connection_number = 1

    def run(self) -> None:  # pragma: no cover - exercised via client tests
        try:
            while not self.server._stop_event.is_set():
                packet = self._recv_packet()
                if packet is None:
                    break
                self._handle(packet)
        except (OSError, ConnectionError, ValueError):
            pass
        finally:
            try:
                self.conn.close()
            except OSError:
                pass

    # -- low level ---------------------------------------------------------

    def _recv_packet(self) -> Packet | None:
        while True:
            frame = read_frame(bytes(self._buffer))
            if frame is not None:
                payload, consumed = frame
                del self._buffer[:consumed]
                return parse_payload(payload)
            try:
                chunk = self.conn.recv(65536)
            except OSError:
                return None
            if not chunk:
                return None
            self._buffer.extend(chunk)

    def _send(self, packet: Packet) -> None:
        self.conn.sendall(encode_packet(packet))

    def _read_data_phase(self) -> bytes:
        data = bytearray()
        while True:
            packet = self._recv_packet()
            if packet is None:
                break
            if isinstance(packet, StartData):
                data.clear()
            elif isinstance(packet, DataPacket):
                data.extend(packet.data)
            elif isinstance(packet, EndData):
                data.extend(packet.data)
                break
        return bytes(data)

    # -- dispatch ----------------------------------------------------------

    def _handle(self, packet: Packet) -> None:
        if isinstance(packet, InitCommandRequest):
            self._send(
                InitCommandAck(
                    connection_number=self._connection_number,
                    guid=DEFAULT_CAMERA_GUID,
                    name=self.state.model,
                    version_minor=0,
                    version_major=1,
                )
            )
        elif isinstance(packet, InitEventRequest):
            self._connection_number = packet.connection_number
            self._send(InitEventAck())
        elif isinstance(packet, OperationRequest):
            self._handle_operation(packet)

    def _handle_operation(self, request: OperationRequest) -> None:
        code = request.operation_code
        transaction_id = request.transaction_id

        if code == OperationCode.OPEN_SESSION:
            self._ok(transaction_id)
        elif code == OperationCode.CLOSE_SESSION:
            self._ok(transaction_id)
        elif code == OperationCode.SET_REMOTE_MODE:
            self._ok(transaction_id)
        elif code == OperationCode.SET_EVENT_MODE:
            self._ok(transaction_id)
        elif code == OperationCode.SET_PROP_VALUE:
            data = self._read_data_phase()
            self._set_prop_value(data)
            self._ok(transaction_id)
        elif code == OperationCode.GET_EVENT_DATA:
            events = self.state.drain_events()
            self._ok(transaction_id, encode_event_data(events))
        elif code == OperationCode.GET_DEVICE_INFO:
            self._ok(transaction_id, encode_device_info(self.state.device_info()))
        elif code == OperationCode.GET_STORAGE_IDS:
            self._ok(transaction_id, encode_storage_ids([self.state.storage.storage_id]))
        elif code == OperationCode.GET_STORAGE_INFO:
            self._ok(transaction_id, encode_storage_info(self.state.storage))
        elif code == OperationCode.GET_NUM_OBJECTS:
            with self.state.lock:
                self._ok(transaction_id, encode_num_objects(len(self.state.images)))
        elif code == OperationCode.GET_OBJECT_HANDLES:
            with self.state.lock:
                handles = [image.handle for image in self.state.images]
            self._ok(transaction_id, encode_object_handles(handles))
        elif code == OperationCode.GET_OBJECT_INFO:
            handle = request.params[0] if request.params else 0
            image = self.state.find_image(handle)
            if image is None:
                self._error(transaction_id, ResponseCode.INVALID_OBJECT_HANDLE)
            else:
                self._ok(
                    transaction_id,
                    encode_object_info(image.as_object(), image.thumbnail),
                )
        elif code == OperationCode.GET_OBJECT:
            handle = request.params[0] if request.params else 0
            image = self.state.find_image(handle)
            if image is None:
                self._error(transaction_id, ResponseCode.INVALID_OBJECT_HANDLE)
            else:
                self._ok(transaction_id, image.data)
        elif code == OperationCode.GET_THUMB:
            handle = request.params[0] if request.params else 0
            image = self.state.find_image(handle)
            if image is None or not image.thumbnail:
                self._error(transaction_id, ResponseCode.NO_THUMBNAIL_PRESENT)
            else:
                self._ok(transaction_id, image.thumbnail)
        elif code == OperationCode.GET_PARTIAL_OBJECT:
            handle, offset, length = (request.params + [0, 0, 0])[:3]
            if (
                self.state.drop_partial_offset is not None
                and offset == self.state.drop_partial_offset
            ):
                self.state.drop_partial_offset = None
                self.conn.close()
                return
            image = self.state.find_image(handle)
            if image is None:
                self._error(transaction_id, ResponseCode.INVALID_OBJECT_HANDLE)
            else:
                self._ok(transaction_id, image.data[offset : offset + length])
        elif code == OperationCode.DELETE_OBJECT:
            handle = request.params[0] if request.params else 0
            with self.state.lock:
                self.state.images = [image for image in self.state.images if image.handle != handle]
            self._ok(transaction_id)
        elif code == OperationCode.START_IMAGE_CAPTURE:
            phase = request.params[0] if request.params else CapturePhase.FOCUS
            if phase == CapturePhase.RELEASE:
                with self.state.lock:
                    self.state.queue_capture()
            self._ok(transaction_id)
        elif code == OperationCode.STOP_IMAGE_CAPTURE:
            self._ok(transaction_id)
        elif code == OperationCode.GET_LIVE_VIEW_IMAGE:
            self._ok(transaction_id, self._build_live_view())
        elif code == OperationCode.SET_TOUCH_AF_POSITION:
            if len(request.params) >= 3:
                self.state.touch_af = (request.params[1], request.params[2])
            self._ok(transaction_id)
        elif code == OperationCode.GET_DEVICE_PROP_VALUE:
            prop_code = request.params[0] if request.params else 0
            value = self.state.properties.get(prop_code, 0)
            self._ok(transaction_id, struct.pack("<I", value))
        else:
            self._error(transaction_id, ResponseCode.OPERATION_NOT_SUPPORTED)

    def _set_prop_value(self, data: bytes) -> None:
        # Canon SetDevicePropValueEx data: [total_length u32][propcode u32][value u32]
        if len(data) < 12:
            return
        prop_code = struct.unpack_from("<I", data, 4)[0]
        value = struct.unpack_from("<I", data, 8)[0]

        with self.state.lock:
            self.state.properties[prop_code] = value
            if prop_code == int(PropertyCode.LIVE_VIEW_OUTPUT):
                self.state.live_view_output = value
            self.state.pending_events.append(PropertyChanged(code=prop_code, value=value))

    def _build_live_view(self) -> bytes:
        with self.state.lock:
            self.state._live_view_counter += 1
            counter = self.state._live_view_counter
            x, y = self.state.touch_af

        jpeg = generate_jpeg(960, 540, counter, f"LIVE {counter}")

        writer = ByteWriter()
        # image segment (id 0x1)
        writer.u32(4 + 4 + len(jpeg)).u32(0x1).raw(jpeg)
        # touch autofocus segment (id 0x8)
        writer.u32(4 + 4 + 24)
        writer.u32(0x8)
        writer.u32(0x30)  # status: tracking
        writer.u32(0x1)
        writer.u32(x)
        writer.u32(y)
        writer.u32(160)
        writer.u32(120)
        return writer.build()

    def _ok(self, transaction_id: int, data: bytes = b"") -> None:
        from ..protocol.packets import EndData as _EndData
        from ..protocol.packets import OperationResponse as _OpResp
        from ..protocol.packets import StartData as _StartData

        if data:
            self._send(_StartData(transaction_id, len(data)))
            self._send(_EndData(transaction_id, data))
        self._send(_OpResp(response_code=int(ResponseCode.OK), transaction_id=transaction_id))

    def _error(self, transaction_id: int, response_code: int) -> None:
        from ..protocol.packets import OperationResponse as _OpResp

        self._send(_OpResp(response_code=int(response_code), transaction_id=transaction_id))


class MockCameraServer:
    """A small TCP server that behaves like a Canon EOS camera."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 15740,
        model: str = "Canon EOS 70D (mock)",
    ) -> None:
        self.host = host
        self.port = port
        self.state = MockCameraState(model=model)
        self._server: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._advertiser = None

    @property
    def address(self) -> tuple[str, int]:
        return self.host, self.port

    def start(self, advertise: bool = False) -> None:
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind((self.host, self.port))
        self._server.listen(8)
        self._server.settimeout(0.5)
        self.port = self._server.getsockname()[1]
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()

        if advertise:
            self._start_advertising()

    def _start_advertising(self) -> None:
        from ..discovery import MdnsAdvertiser

        suffix = "".join(ch for ch in self.state.serial if ch.isdigit())[-6:] or "000000"
        instance = f"ICPO-WFTEOSSystemService{suffix}"
        advert_host = "127.0.0.1" if self.host in {"0.0.0.0", ""} else self.host
        self._advertiser = MdnsAdvertiser(advert_host, self.port, instance)
        try:
            self._advertiser.start()
        except Exception:  # pragma: no cover - depends on the network
            self._advertiser = None

    def _accept_loop(self) -> None:
        assert self._server is not None
        while not self._stop_event.is_set():
            try:
                conn, addr = self._server.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            _ConnectionHandler(self, conn, addr).start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._advertiser is not None:
            try:
                self._advertiser.stop()
            except Exception:  # pragma: no cover
                pass
            self._advertiser = None
        if self._server is not None:
            try:
                self._server.close()
            except OSError:
                pass
        if self._thread is not None:
            self._thread.join(timeout=2)

    def __enter__(self) -> MockCameraServer:
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()
