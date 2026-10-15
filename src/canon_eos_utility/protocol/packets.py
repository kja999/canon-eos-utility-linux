"""Encoding and decoding of PTP/IP packets.

Every PTP/IP packet is a little-endian length-prefixed frame::

    +--------+--------+---------------------------+
    | length | type   | type specific payload ... |
    | uint32 | uint32 |                           |
    +--------+--------+---------------------------+

``length`` counts the whole frame including the length field itself.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

from ..constants import PacketType


class ProtocolError(Exception):
    """Raised when a malformed PTP/IP packet is encountered."""


class ByteReader:
    """Small little-endian reader over a bytes buffer."""

    __slots__ = ("_data", "_offset")

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._offset = 0

    @property
    def offset(self) -> int:
        return self._offset

    @property
    def remaining(self) -> int:
        return len(self._data) - self._offset

    def read(self, count: int) -> bytes:
        if count < 0 or count > self.remaining:
            raise ProtocolError(f"want {count} bytes, only {self.remaining} remaining")
        value = self._data[self._offset : self._offset + count]
        self._offset += count
        return value

    def u8(self) -> int:
        return self.read(1)[0]

    def u16(self) -> int:
        return struct.unpack_from("<H", self.read(2))[0]

    def u32(self) -> int:
        return struct.unpack_from("<I", self.read(4))[0]

    def u64(self) -> int:
        return struct.unpack_from("<Q", self.read(8))[0]

    def utf16_string(self) -> str:
        """Read a NUL terminated UTF-16LE string."""
        chars: list[str] = []
        while self.remaining >= 2:
            (code,) = struct.unpack_from("<H", self._data, self._offset)
            self._offset += 2
            if code == 0:
                return "".join(chars)
            chars.append(chr(code))
        raise ProtocolError("unterminated UTF-16 string")

    def ptp_string(self) -> str:
        """Read a PTP string (UINT8 char count incl. NUL, then UTF-16LE)."""
        length = self.u8()
        if length == 0:
            return ""
        return self.utf16_string()

    def rest(self) -> bytes:
        return self.read(self.remaining)


class ByteWriter:
    """Little-endian writer mirroring :class:`ByteReader`."""

    __slots__ = ("_parts",)

    def __init__(self) -> None:
        self._parts: list[bytes] = []

    def raw(self, data: bytes) -> ByteWriter:
        self._parts.append(data)
        return self

    def u8(self, value: int) -> ByteWriter:
        self._parts.append(struct.pack("<B", value & 0xFF))
        return self

    def u16(self, value: int) -> ByteWriter:
        self._parts.append(struct.pack("<H", value & 0xFFFF))
        return self

    def u32(self, value: int) -> ByteWriter:
        self._parts.append(struct.pack("<I", value & 0xFFFFFFFF))
        return self

    def u64(self, value: int) -> ByteWriter:
        self._parts.append(struct.pack("<Q", value & 0xFFFFFFFFFFFFFFFF))
        return self

    def utf16_string(self, value: str) -> ByteWriter:
        """Write a NUL terminated UTF-16LE string (no length prefix)."""
        payload = value.encode("utf-16-le") + b"\x00\x00"
        return self.raw(payload)

    def ptp_string(self, value: str) -> ByteWriter:
        """Write a PTP string (UINT8 char count incl. NUL, then UTF-16LE)."""
        if not value:
            return self.u8(0)
        self.u8(len(value) + 1)
        return self.raw(value.encode("utf-16-le") + b"\x00\x00")

    def build(self) -> bytes:
        return b"".join(self._parts)


# ---------------------------------------------------------------------------
# Packet model
# ---------------------------------------------------------------------------


@dataclass
class Packet:
    """Base class for decoded packets."""

    PACKET_TYPE: int = field(init=False, default=0)

    def payload(self) -> bytes:  # pragma: no cover - overridden
        raise NotImplementedError


@dataclass
class InitCommandRequest(Packet):
    guid: bytes
    name: str
    version: int = 1
    PACKET_TYPE: int = field(init=False, default=int(PacketType.INIT_COMMAND_REQUEST))

    def payload(self) -> bytes:
        w = ByteWriter()
        w.u32(self.PACKET_TYPE).raw(self.guid).utf16_string(self.name).u32(self.version)
        return w.build()


@dataclass
class InitCommandAck(Packet):
    connection_number: int
    guid: bytes
    name: str
    version_minor: int = 0
    version_major: int = 1
    PACKET_TYPE: int = field(init=False, default=int(PacketType.INIT_COMMAND_ACK))

    @property
    def version(self) -> str:
        return f"{self.version_major}.{self.version_minor}"

    def payload(self) -> bytes:
        w = ByteWriter()
        w.u32(self.PACKET_TYPE)
        w.u32(self.connection_number)
        w.raw(self.guid)
        w.utf16_string(self.name)
        w.u16(self.version_minor).u16(self.version_major)
        return w.build()


@dataclass
class InitEventRequest(Packet):
    connection_number: int
    PACKET_TYPE: int = field(init=False, default=int(PacketType.INIT_EVENT_REQUEST))

    def payload(self) -> bytes:
        return ByteWriter().u32(self.PACKET_TYPE).u32(self.connection_number).build()


@dataclass
class InitEventAck(Packet):
    PACKET_TYPE: int = field(init=False, default=int(PacketType.INIT_EVENT_ACK))

    def payload(self) -> bytes:
        return ByteWriter().u32(self.PACKET_TYPE).build()


@dataclass
class InitFail(Packet):
    error_code: int
    PACKET_TYPE: int = field(init=False, default=int(PacketType.INIT_FAIL))

    def payload(self) -> bytes:
        return ByteWriter().u32(self.PACKET_TYPE).u32(self.error_code).build()


@dataclass
class OperationRequest(Packet):
    data_phase: int
    operation_code: int
    transaction_id: int
    params: list[int] = field(default_factory=list)
    PACKET_TYPE: int = field(init=False, default=int(PacketType.OPERATION_REQUEST))

    def payload(self) -> bytes:
        w = ByteWriter()
        w.u32(self.PACKET_TYPE)
        w.u32(self.data_phase)
        w.u16(self.operation_code)
        w.u32(self.transaction_id)
        for param in self.params:
            w.u32(param)
        return w.build()


@dataclass
class OperationResponse(Packet):
    response_code: int
    transaction_id: int
    params: list[int] = field(default_factory=list)
    #: Data reassembled from an accompanying data-in phase (not on the wire).
    data: bytes = b""
    PACKET_TYPE: int = field(init=False, default=int(PacketType.OPERATION_RESPONSE))

    def payload(self) -> bytes:
        w = ByteWriter()
        w.u32(self.PACKET_TYPE)
        w.u16(self.response_code)
        w.u32(self.transaction_id)
        for param in self.params:
            w.u32(param)
        return w.build()


@dataclass
class StartData(Packet):
    transaction_id: int
    total_length: int
    PACKET_TYPE: int = field(init=False, default=int(PacketType.START_DATA))

    def payload(self) -> bytes:
        w = ByteWriter()
        w.u32(self.PACKET_TYPE).u32(self.transaction_id).u64(self.total_length)
        return w.build()


@dataclass
class DataPacket(Packet):
    transaction_id: int
    data: bytes
    PACKET_TYPE: int = field(init=False, default=int(PacketType.DATA))

    def payload(self) -> bytes:
        w = ByteWriter()
        w.u32(self.PACKET_TYPE).u32(self.transaction_id).raw(self.data)
        return w.build()


@dataclass
class EndData(Packet):
    transaction_id: int
    data: bytes
    PACKET_TYPE: int = field(init=False, default=int(PacketType.END_DATA))

    def payload(self) -> bytes:
        w = ByteWriter()
        w.u32(self.PACKET_TYPE).u32(self.transaction_id).raw(self.data)
        return w.build()


@dataclass
class EventPacket(Packet):
    event_code: int
    transaction_id: int
    params: list[int] = field(default_factory=list)
    PACKET_TYPE: int = field(init=False, default=int(PacketType.EVENT))

    def payload(self) -> bytes:
        w = ByteWriter()
        w.u32(self.PACKET_TYPE).u16(self.event_code).u32(self.transaction_id)
        for param in self.params:
            w.u32(param)
        return w.build()


@dataclass
class Ping(Packet):
    PACKET_TYPE: int = field(init=False, default=int(PacketType.PING))

    def payload(self) -> bytes:
        return ByteWriter().u32(self.PACKET_TYPE).build()


@dataclass
class Pong(Packet):
    PACKET_TYPE: int = field(init=False, default=int(PacketType.PONG))

    def payload(self) -> bytes:
        return ByteWriter().u32(self.PACKET_TYPE).build()


def encode_packet(packet: Packet) -> bytes:
    """Serialize a packet, prepending the 4 byte length prefix."""
    body = packet.payload()
    return struct.pack("<I", len(body) + 4) + body


def parse_payload(payload: bytes) -> Packet:
    """Decode a packet payload (everything after the length field)."""
    reader = ByteReader(payload)
    packet_type = reader.u32()

    if packet_type == PacketType.INIT_COMMAND_REQUEST:
        guid = reader.read(16)
        name = reader.utf16_string()
        version = reader.u32() if reader.remaining >= 4 else 1
        return InitCommandRequest(guid=guid, name=name, version=version)
    if packet_type == PacketType.INIT_COMMAND_ACK:
        connection_number = reader.u32()
        guid = reader.read(16)
        name = reader.utf16_string()
        version_minor = reader.u16() if reader.remaining >= 2 else 0
        version_major = reader.u16() if reader.remaining >= 2 else 1
        return InitCommandAck(
            connection_number=connection_number,
            guid=guid,
            name=name,
            version_minor=version_minor,
            version_major=version_major,
        )
    if packet_type == PacketType.INIT_EVENT_REQUEST:
        return InitEventRequest(connection_number=reader.u32())
    if packet_type == PacketType.INIT_EVENT_ACK:
        return InitEventAck()
    if packet_type == PacketType.INIT_FAIL:
        return InitFail(error_code=reader.u32())
    if packet_type == PacketType.OPERATION_REQUEST:
        data_phase = reader.u32()
        operation_code = reader.u16()
        transaction_id = reader.u32()
        params = _read_u32_list(reader)
        return OperationRequest(
            data_phase=data_phase,
            operation_code=operation_code,
            transaction_id=transaction_id,
            params=params,
        )
    if packet_type == PacketType.OPERATION_RESPONSE:
        response_code = reader.u16()
        transaction_id = reader.u32()
        params = _read_u32_list(reader)
        return OperationResponse(
            response_code=response_code, transaction_id=transaction_id, params=params
        )
    if packet_type == PacketType.EVENT:
        event_code = reader.u16()
        transaction_id = reader.u32()
        params = _read_u32_list(reader)
        return EventPacket(event_code=event_code, transaction_id=transaction_id, params=params)
    if packet_type == PacketType.START_DATA:
        return StartData(transaction_id=reader.u32(), total_length=reader.u64())
    if packet_type == PacketType.DATA:
        return DataPacket(transaction_id=reader.u32(), data=reader.rest())
    if packet_type == PacketType.END_DATA:
        return EndData(transaction_id=reader.u32(), data=reader.rest())
    if packet_type == PacketType.PING:
        return Ping()
    if packet_type == PacketType.PONG:
        return Pong()

    raise ProtocolError(f"unknown packet type 0x{packet_type:08X}")


def _read_u32_list(reader: ByteReader) -> list[int]:
    values: list[int] = []
    while reader.remaining >= 4:
        values.append(reader.u32())
    return values


def read_frame(buffer: bytes) -> tuple[bytes, int] | None:
    """Extract one frame payload from ``buffer``.

    Returns ``(payload, consumed)`` where ``payload`` excludes the length
    prefix, or ``None`` when the buffer does not yet hold a full frame.
    """
    if len(buffer) < 4:
        return None
    (length,) = struct.unpack_from("<I", buffer, 0)
    if length < 4:
        raise ProtocolError(f"invalid frame length {length}")
    if len(buffer) < length:
        return None
    return buffer[4:length], length
