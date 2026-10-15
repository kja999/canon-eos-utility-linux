"""Exception types used across the application."""

from __future__ import annotations

from .constants import ResponseCode


class CameraError(Exception):
    """An operation failed or the camera returned an error response."""

    def __init__(self, message: str, response_code: int | None = None) -> None:
        super().__init__(message)
        self.response_code = response_code

    @classmethod
    def from_response(cls, response_code: int, operation: str) -> CameraError:
        try:
            name = ResponseCode(response_code).name
        except ValueError:
            name = f"0x{response_code:04X}"
        return cls(f"{operation} failed: {name}", response_code=response_code)


class NotConnectedError(CameraError):
    """No PTP/IP session is open."""
