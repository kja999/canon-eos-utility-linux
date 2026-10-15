"""Thin socket transport for a single PTP/IP channel."""

from __future__ import annotations

import socket
import struct

from .packets import Packet, encode_packet, parse_payload, read_frame


class TransportError(Exception):
    """Raised for socket level failures."""


class Transport:
    """A single PTP/IP channel (either the command or the event socket)."""

    def __init__(
        self,
        host: str,
        port: int,
        timeout: float = 10.0,
        connect_timeout: float | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self._buffer = bytearray()
        self._queue: list[Packet] = []
        try:
            self._sock = socket.create_connection((host, port), timeout=connect_timeout or timeout)
        except OSError as exc:  # pragma: no cover - network dependent
            raise TransportError(f"cannot connect to {host}:{port}: {exc}") from exc
        self._sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._sock.settimeout(timeout)

    def send(self, packet: Packet) -> None:
        try:
            self._sock.sendall(encode_packet(packet))
        except OSError as exc:  # pragma: no cover
            raise TransportError(f"send failed: {exc}") from exc

    def recv(self) -> Packet:
        """Return the next decoded packet, blocking until one is available."""
        if self._queue:
            return self._queue.pop(0)

        while True:
            frame = read_frame(bytes(self._buffer))
            if frame is not None:
                payload, consumed = frame
                del self._buffer[:consumed]
                packet = parse_payload(payload)
                return packet

            try:
                chunk = self._sock.recv(65536)
            except TimeoutError as exc:
                raise TransportError(f"timed out waiting for data: {exc}") from exc
            except OSError as exc:  # pragma: no cover
                raise TransportError(f"receive failed: {exc}") from exc
            if not chunk:
                raise TransportError("connection closed by camera")
            self._buffer.extend(chunk)

    def send_recv(self, packet: Packet) -> Packet:
        self.send(packet)
        return self.recv()

    @property
    def closed(self) -> bool:
        return self._sock.fileno() == -1

    def close(self) -> None:
        try:
            self._sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        finally:
            self._sock.close()


def frame_length(buffer: bytes) -> int | None:  # pragma: no cover - convenience
    if len(buffer) < 4:
        return None
    return struct.unpack_from("<I", buffer, 0)[0]
