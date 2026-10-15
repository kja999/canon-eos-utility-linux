"""Decoders for the payloads carried inside PTP/IP data phases."""

from __future__ import annotations

from dataclasses import dataclass

from ..constants import EventCode, PropertyCode
from ..models import (
    AllowedValuesChanged,
    CameraEvent,
    CameraObject,
    DeviceInfo,
    ObjectAdded,
    PropertyChanged,
    RawEvent,
    StorageInfo,
)
from .packets import ByteReader, ByteWriter, ProtocolError

JPEG_START = b"\xff\xd8\xff"
JPEG_END = b"\xff\xd9"


# ---------------------------------------------------------------------------
# Device / storage / object metadata
# ---------------------------------------------------------------------------


def parse_device_info(data: bytes) -> DeviceInfo:
    reader = ByteReader(data)
    info = DeviceInfo()
    info.standard_version = reader.u16()
    info.vendor_extension_id = reader.u32()
    info.vendor_extension_version = reader.u16()
    info.vendor_extension_description = reader.ptp_string()
    info.functional_mode = reader.u16()
    info.operations = _read_u16_array(reader)
    info.events = _read_u16_array(reader)
    info.properties = _read_u16_array(reader)
    info.capture_formats = _read_u16_array(reader)
    info.image_formats = _read_u16_array(reader)
    info.manufacturer = reader.ptp_string()
    info.model = reader.ptp_string()
    info.device_version = reader.ptp_string()
    info.serial_number = reader.ptp_string()
    return info


def parse_storage_ids(data: bytes) -> list[int]:
    return _read_u32_array(data)


def parse_num_objects(data: bytes) -> int:
    return ByteReader(data).u32()


def parse_object_handles(data: bytes) -> list[int]:
    return _read_u32_array(data)


def parse_storage_info(data: bytes) -> StorageInfo:
    reader = ByteReader(data)
    reader.u16()  # storage type
    reader.u16()  # filesystem type
    reader.u16()  # access capability
    max_capacity = reader.u64()
    free_space = reader.u64()
    free_images = reader.u32()
    description = reader.ptp_string()
    reader.ptp_string()  # volume label
    return StorageInfo(
        storage_id=0,
        max_capacity=max_capacity,
        free_space=free_space,
        max_objects=free_images,
        free_objects=free_images,
        description=description,
    )


def parse_object_info(data: bytes) -> CameraObject:
    reader = ByteReader(data)
    storage_id = reader.u32()
    fmt = reader.u16()
    protection = reader.u16()
    size = reader.u32()
    reader.u16()  # thumb format
    reader.u32()  # thumb compressed size
    reader.u32()  # thumb width
    reader.u32()  # thumb height
    width = reader.u32()
    height = reader.u32()
    reader.u32()  # bit depth
    reader.u32()  # parent object
    reader.u16()  # association type
    reader.u32()  # association description
    reader.u32()  # sequence number
    filename = reader.ptp_string()
    capture_date = reader.ptp_string() if reader.remaining else ""
    return CameraObject(
        handle=0,
        storage_id=storage_id,
        format=fmt,
        size=size,
        filename=filename,
        capture_date=capture_date,
        width=width,
        height=height,
        protection_status=protection,
    )


# ---------------------------------------------------------------------------
# Canon event data (GetEventData response)
# ---------------------------------------------------------------------------


def parse_event_data(data: bytes) -> list[CameraEvent]:
    """Parse the segment stream returned by ``GetEventData`` (0x9116)."""
    reader = ByteReader(data)
    events: list[CameraEvent] = []

    # Each segment: u32 length (incl. itself), u32 event code, payload.
    while reader.remaining > 8:
        length = reader.u32()
        if length < 4 or length - 4 > reader.remaining:
            break
        segment = ByteReader(reader.read(length - 4))
        _parse_event_segment(segment, events)

    return events


def _parse_event_segment(segment: ByteReader, events: list[CameraEvent]) -> None:
    if segment.remaining < 4:
        return
    event_code = segment.u32()

    if event_code == EventCode.PROPERTY_CHANGED:
        if segment.remaining >= 8:
            code = segment.u32()
            value = segment.u32()
            events.append(PropertyChanged(code=code, value=value))
        return

    if event_code == EventCode.ALLOWED_VALUES_CHANGED:
        if segment.remaining >= 12:
            code = segment.u32()
            segment.u32()  # unknown
            count = segment.u32()
            values = [segment.u32() for _ in range(count) if segment.remaining >= 4]
            events.append(AllowedValuesChanged(code=code, values=values))
        return

    if event_code == EventCode.OBJECT_ADDED and segment.remaining >= 4:
        events.append(ObjectAdded(handle=segment.u32()))
        return

    events.append(RawEvent(event_code=event_code, data=segment.rest()))


# ---------------------------------------------------------------------------
# Live view payload
# ---------------------------------------------------------------------------


@dataclass
class TouchAF:
    status: int
    x: int
    y: int
    width: int
    height: int


@dataclass
class LiveViewFrame:
    jpeg: bytes | None = None
    touch_af: TouchAF | None = None
    histogram: bytes | None = None


def extract_jpeg(data: bytes) -> bytes | None:
    start = data.find(JPEG_START)
    if start == -1:
        return None
    end = data.rfind(JPEG_END)
    if end == -1 or end < start:
        return None
    return data[start : end + 2]


def parse_live_view(data: bytes) -> LiveViewFrame:
    """Parse a ``GetLiveViewImage`` (0x9153) response.

    The JPEG frame is always extracted by scanning for SOI/EOI markers which is
    more robust across camera models; the touch-AF segment is decoded from the
    documented segment layout when present.
    """
    frame = LiveViewFrame(jpeg=extract_jpeg(data))

    reader = ByteReader(data)
    while reader.remaining > 8:
        length = reader.u32()
        if length < 8 or length - 4 > reader.remaining:
            break
        segment = ByteReader(reader.read(length - 4))
        if segment.remaining < 4:
            continue
        segment_id = segment.u32()
        if segment_id == 0x8 and segment.remaining >= 24:
            http_status = segment.u32()
            segment.u32()  # unknown
            x = segment.u32()
            y = segment.u32()
            width = segment.u32()
            height = segment.u32()
            frame.touch_af = TouchAF(status=http_status, x=x, y=y, width=width, height=height)
        elif segment_id == 0x11:
            frame.histogram = segment.rest()

    return frame


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_u32_array(data: bytes) -> list[int]:
    reader = ByteReader(data)
    count = reader.u32()
    values: list[int] = []
    for _ in range(count):
        if reader.remaining < 4:
            raise ProtocolError("truncated UINT32 array")
        values.append(reader.u32())
    return values


def _read_u16_array(reader: ByteReader) -> list[int]:
    count = reader.u32()
    values: list[int] = []
    for _ in range(count):
        if reader.remaining < 2:
            raise ProtocolError("truncated UINT16 array")
        values.append(reader.u16())
    return values


#: Property codes that have a defined control widget in the UI.
KNOWN_CONTROL_PROPERTIES = (
    PropertyCode.APERTURE,
    PropertyCode.SHUTTER_SPEED,
    PropertyCode.ISO,
    PropertyCode.WHITE_BALANCE,
)


# ---------------------------------------------------------------------------
# Encoders (used by the mock camera and the test-suite)
# ---------------------------------------------------------------------------


def _write_u16_array(writer: ByteWriter, values: list[int]) -> None:
    writer.u32(len(values))
    for value in values:
        writer.u16(value)


def _write_u32_array(writer: ByteWriter, values: list[int]) -> None:
    writer.u32(len(values))
    for value in values:
        writer.u32(value)


def encode_device_info(info: DeviceInfo) -> bytes:
    w = ByteWriter()
    w.u16(info.standard_version)
    w.u32(info.vendor_extension_id)
    w.u16(info.vendor_extension_version)
    w.ptp_string(info.vendor_extension_description)
    w.u16(info.functional_mode)
    _write_u16_array(w, info.operations)
    _write_u16_array(w, info.events)
    _write_u16_array(w, info.properties)
    _write_u16_array(w, info.capture_formats)
    _write_u16_array(w, info.image_formats)
    w.ptp_string(info.manufacturer)
    w.ptp_string(info.model)
    w.ptp_string(info.device_version)
    w.ptp_string(info.serial_number)
    return w.build()


def encode_storage_info(info: StorageInfo) -> bytes:
    w = ByteWriter()
    w.u16(0x0003)  # fixed RAM storage
    w.u16(0x0002)  # DOS FAT filesystem
    w.u16(0x0000)  # read-write access
    w.u64(info.max_capacity)
    w.u64(info.free_space)
    w.u32(info.free_objects)
    w.ptp_string(info.description)
    w.ptp_string("")  # volume label
    return w.build()


def encode_object_info(obj: CameraObject, thumb: bytes = b"") -> bytes:
    w = ByteWriter()
    w.u32(obj.storage_id)
    w.u16(obj.format)
    w.u16(obj.protection_status)
    w.u32(obj.size)
    w.u16(0x3801 if thumb else 0x0000)  # thumbnail format
    w.u32(len(thumb))
    w.u32(160)
    w.u32(120)
    w.u32(obj.width)
    w.u32(obj.height)
    w.u32(0)  # bit depth
    w.u32(0)  # parent object
    w.u16(0)  # association type
    w.u32(0)  # association description
    w.u32(0)  # sequence number
    w.ptp_string(obj.filename)
    w.ptp_string(obj.capture_date)
    w.ptp_string(obj.capture_date)  # modification date
    w.ptp_string("")  # keywords
    return w.build()


def encode_storage_ids(storage_ids: list[int]) -> bytes:
    w = ByteWriter()
    _write_u32_array(w, storage_ids)
    return w.build()


def encode_num_objects(count: int) -> bytes:
    return ByteWriter().u32(count).build()


def encode_object_handles(handles: list[int]) -> bytes:
    w = ByteWriter()
    _write_u32_array(w, handles)
    return w.build()


def encode_event_data(events: list[CameraEvent]) -> bytes:
    """Encode a list of events as a Canon ``GetEventData`` payload."""
    w = ByteWriter()
    for event in events:
        if isinstance(event, PropertyChanged):
            w.u32(16).u32(int(EventCode.PROPERTY_CHANGED)).u32(event.code).u32(event.value)
        elif isinstance(event, AllowedValuesChanged):
            w.u32(20 + 4 * len(event.values))
            w.u32(int(EventCode.ALLOWED_VALUES_CHANGED))
            w.u32(event.code)
            w.u32(0)
            w.u32(len(event.values))
            for value in event.values:
                w.u32(value)
        elif isinstance(event, ObjectAdded):
            w.u32(12).u32(int(EventCode.OBJECT_ADDED)).u32(event.handle)
        else:  # RawEvent
            w.u32(8 + len(event.data)).u32(event.event_code).raw(event.data)
    w.u32(8).u32(0x00000000)  # end marker
    return w.build()
