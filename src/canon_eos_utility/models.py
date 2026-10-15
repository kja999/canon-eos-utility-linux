"""Plain data models shared between the protocol layer and the UI."""

from __future__ import annotations

from dataclasses import dataclass, field

from .constants import (
    OBJECT_FORMAT_NAMES,
    PROPERTY_NAMES,
    ObjectFormat,
    property_value_label,
)

#: Format codes treated as still images / movies.  Filename extensions are used
#: as a fallback because some bodies report non-standard vendor codes.
_IMAGE_FORMATS = {
    int(ObjectFormat.EXIF_JPEG),
    int(ObjectFormat.JFIF),
    int(ObjectFormat.JPEG),
    int(ObjectFormat.PNG),
    int(ObjectFormat.DNG),
    int(ObjectFormat.TIFF),
    int(ObjectFormat.TIFF_EP),
    int(ObjectFormat.CRW),
    int(ObjectFormat.CR2),
    int(ObjectFormat.CR3),
}
_MOVIE_FORMATS = {
    int(ObjectFormat.MOV),
    int(ObjectFormat.MOV2),
    int(ObjectFormat.MP4),
    int(ObjectFormat.AVI),
}
_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".dng", ".crw", ".cr2", ".cr3"}
_MOVIE_EXTENSIONS = {".mov", ".mp4", ".avi", ".m4v"}


def _format_capture_date(value: str) -> str:
    """Convert a PTP date (``20230703T163933.0``) to ``2023-07-03 16:39:33``."""
    if len(value) >= 15 and value[8] == "T":
        try:
            return f"{value[0:4]}-{value[4:6]}-{value[6:8]} {value[9:11]}:{value[11:13]}:{value[13:15]}"
        except (IndexError, ValueError):
            return value
    return value


@dataclass
class CameraInfo:
    """Identification of a connected camera."""

    guid: bytes
    name: str
    connection_number: int
    version: str
    address: str
    manufacturer: str = ""
    model: str = ""
    device_version: str = ""
    serial_number: str = ""

    @property
    def display_name(self) -> str:
        return self.model or self.name or "Canon camera"


@dataclass
class StorageInfo:
    storage_id: int
    max_capacity: int
    free_space: int
    max_objects: int
    free_objects: int
    description: str

    @property
    def capacity_gib(self) -> float:
        return self.max_capacity / (1024**3)

    @property
    def free_gib(self) -> float:
        return self.free_space / (1024**3)


@dataclass
class CameraObject:
    """An object (photo / movie / folder) stored on the camera."""

    handle: int
    storage_id: int
    format: int
    size: int
    filename: str
    capture_date: str = ""
    width: int = 0
    height: int = 0
    protection_status: int = 0

    @property
    def format_name(self) -> str:
        return OBJECT_FORMAT_NAMES.get(self.format, f"0x{self.format:04X}")

    @property
    def capture_date_display(self) -> str:
        return _format_capture_date(self.capture_date)

    @property
    def _extension(self) -> str:
        name = self.filename.lower()
        dot = name.rfind(".")
        return name[dot:] if dot != -1 else ""

    @property
    def is_image(self) -> bool:
        if self.format in _IMAGE_FORMATS:
            return True
        return self._extension in _IMAGE_EXTENSIONS

    @property
    def is_movie(self) -> bool:
        if self.format in _MOVIE_FORMATS:
            return True
        return self._extension in _MOVIE_EXTENSIONS

    @property
    def is_folder(self) -> bool:
        return self.format == ObjectFormat.ASSOCIATION


@dataclass(frozen=True)
class PropertyValue:
    """A camera setting value (e.g. ISO)."""

    code: int
    value: int

    @property
    def label(self) -> str:
        return property_value_label(self.code, self.value)

    @property
    def name(self) -> str:
        return PROPERTY_NAMES.get(self.code, f"0x{self.code:04X}")


@dataclass
class DeviceInfo:
    standard_version: int = 0
    vendor_extension_id: int = 0
    vendor_extension_version: int = 0
    vendor_extension_description: str = ""
    functional_mode: int = 0
    operations: list[int] = field(default_factory=list)
    events: list[int] = field(default_factory=list)
    properties: list[int] = field(default_factory=list)
    capture_formats: list[int] = field(default_factory=list)
    image_formats: list[int] = field(default_factory=list)
    manufacturer: str = ""
    model: str = ""
    device_version: str = ""
    serial_number: str = ""

    def supports(self, operation_code: int) -> bool:
        return operation_code in self.operations


# ---------------------------------------------------------------------------
# Asynchronous events
# ---------------------------------------------------------------------------


@dataclass
class PropertyChanged:
    code: int
    value: int


@dataclass
class AllowedValuesChanged:
    code: int
    values: list[int]


@dataclass
class ObjectAdded:
    handle: int


@dataclass
class RawEvent:
    event_code: int
    data: bytes = b""


CameraEvent = PropertyChanged | AllowedValuesChanged | ObjectAdded | RawEvent


def is_supported_property(code: int) -> bool:
    return code in PROPERTY_NAMES
