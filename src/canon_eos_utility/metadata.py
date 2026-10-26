"""Extract EXIF / metadata from downloaded media.

Uses the pure-Python :mod:`exif` package for still images.  Canon's CR3 raw
files are an ISO-BMFF container that stores EXIF in ``CMT1``/``CMT2``/``CMT4``
boxes as standalone TIFF blocks, which we feed to the ``exif`` library.  Movies
have no EXIF, so their creation time is read from the MP4 ``mvhd`` box and any
remaining fields fall back to the camera's PTP metadata.
"""

from __future__ import annotations

import datetime
import io
import struct
from dataclasses import dataclass, field
from typing import Any

# Seconds between the MP4/QuickTime epoch (1904-01-01) and the Unix epoch.
_MP4_EPOCH_OFFSET = 2_082_844_800

_CMT_BOXES = (b"CMT1", b"CMT2", b"CMT4")
_EXIF_HEADER = b"Exif\x00\x00"


@dataclass
class MediaMetadata:
    tags: dict[str, Any] = field(default_factory=dict)
    width: int | None = None
    height: int | None = None
    taken: datetime.datetime | None = None
    make: str = ""
    model: str = ""
    lens_model: str = ""
    iso: int | None = None
    f_number: float | None = None
    exposure_time: float | None = None
    focal_length: float | None = None
    orientation: int | None = None
    source: str = ""  # "exif", "cr3", "mp4" or "fallback"

    def as_context(self) -> dict[str, Any]:
        """Values exposed to the file-naming template under ``exif.*``."""
        context: dict[str, Any] = dict(self.tags)
        context.update(
            {
                "make": self.make,
                "model": self.model,
                "lens_model": self.lens_model,
                "iso": self.iso,
                "f_number": self.f_number,
                "exposure_time": self.exposure_time,
                "focal_length": self.focal_length,
                "width": self.width,
                "height": self.height,
                "source": self.source,
            }
        )
        if self.taken is not None:
            context["datetime_original"] = self.taken.strftime("%Y:%m:%d %H:%M:%S")
        return context


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def read_metadata(
    path: str,
    fallback_datetime: datetime.datetime | None = None,
    fallback_size: tuple[int | None, int | None] = (None, None),
) -> MediaMetadata:
    """Read metadata from a downloaded file, never raising."""
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError:
        return MediaMetadata(taken=fallback_datetime, source="fallback")

    metadata = _extract(data, fallback_datetime)
    if metadata.width is None:
        metadata.width = fallback_size[0]
    if metadata.height is None:
        metadata.height = fallback_size[1]
    if metadata.taken is None:
        metadata.taken = fallback_datetime
    return metadata


def parse_ptp_datetime(value: str) -> datetime.datetime | None:
    """Parse Canon's PTP date ``20260723T113741.0`` into a datetime."""
    if len(value) >= 15 and value[8] == "T":
        try:
            return datetime.datetime(
                int(value[0:4]),
                int(value[4:6]),
                int(value[6:8]),
                int(value[9:11]),
                int(value[11:13]),
                int(value[13:15]),
            )
        except ValueError:
            return None
    return None


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _extract(data: bytes, fallback_datetime: datetime.datetime | None) -> MediaMetadata:
    kind = _kind(data)

    if kind == "jpeg":
        tags = _read_direct_tags(data)
        if tags:
            return _from_tags(tags, source="exif")

    if kind == "tiff":
        tags = _read_wrapped_tags(data)
        if tags:
            return _from_tags(tags, source="exif")

    if kind == "cr3":
        tags = _read_cr3_tags(data)
        if tags:
            return _from_tags(tags, source="cr3")

    if kind == "mp4":
        taken = _read_mp4_datetime(data)
        return MediaMetadata(taken=taken, source="mp4" if taken else "fallback")

    # Unknown: last-ditch attempt at a direct APP1 parse.
    tags = _read_direct_tags(data)
    if tags:
        return _from_tags(tags, source="exif")
    return MediaMetadata(source="fallback")


def _kind(data: bytes) -> str:
    if data[:2] == b"\xff\xd8":
        return "jpeg"
    if data[:4] in (b"II*\x00", b"MM\x00*"):
        return "tiff"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        brand = data[8:12]
        if brand.startswith(b"crx") or b"crx" in data[8:20]:
            return "cr3"
        return "mp4"
    return "unknown"


def _exif_image(payload: bytes):
    try:
        from exif import Image as ExifImage

        return ExifImage(io.BytesIO(payload))
    except Exception:
        return None


def _read_direct_tags(data: bytes) -> dict[str, Any]:
    image = _exif_image(data)
    if image is None or not getattr(image, "has_exif", False):
        return {}
    return _collect_tags(image)


def _read_wrapped_tags(tiff: bytes) -> dict[str, Any]:
    image = _exif_image(_wrap_tiff_as_app1(tiff))
    if image is None or not getattr(image, "has_exif", False):
        return {}
    return _collect_tags(image)


def _read_cr3_tags(data: bytes) -> dict[str, Any]:
    tags: dict[str, Any] = {}
    for box in _CMT_BOXES:
        tiff = _find_box(data, box)
        if not tiff:
            continue
        image = _exif_image(_wrap_tiff_as_app1(tiff))
        if image is None or not getattr(image, "has_exif", False):
            continue
        for key, value in _collect_tags(image).items():
            tags.setdefault(key, value)
    return tags


def _collect_tags(image) -> dict[str, Any]:
    tags: dict[str, Any] = {}
    try:
        names = image.list_all()
    except Exception:
        return tags
    for name in names:
        try:
            value = image.get(name)
        except Exception:
            continue
        if value is None:
            continue
        tags[name] = _normalise_value(value)
    return tags


def _normalise_value(value: Any) -> Any:
    if isinstance(value, (str, int, float, bytes)):
        return value
    if isinstance(value, (list, tuple)):
        return tuple(value)
    # Enums (Orientation, Flash, ...) expose their integer via .value
    enum_value = getattr(value, "value", None)
    if isinstance(enum_value, int):
        return enum_value
    return str(value)


def _find_box(data: bytes, box_type: bytes) -> bytes | None:
    """Return the body of the first ISO-BMFF ``box_type`` box found."""
    index = data.find(box_type)
    if index < 4:
        return None
    size = int.from_bytes(data[index - 4 : index], "big")
    if size in (0, 1) or index - 4 + size > len(data):
        return None
    return data[index + 4 : index - 4 + size]


def _wrap_tiff_as_app1(tiff: bytes) -> bytes:
    """Wrap a raw TIFF block in a minimal APP1 segment the ``exif`` lib accepts.

    The JPEG EXIF APP1 segment has a 16-bit length field (max 65535 bytes), so
    only the first portion of the TIFF data is wrapped.  The metadata (IFDs) are
    at the beginning of the file, so truncating the image data at the end is safe.
    """
    max_tiff = 65535 - len(_EXIF_HEADER) - 2  # 65535 - 6 - 2 = 65527
    segment = _EXIF_HEADER + tiff[:max_tiff]
    return b"\xff\xe1" + struct.pack(">H", len(segment)) + segment + b"\xff\xd9"


def _read_mp4_datetime(data: bytes) -> datetime.datetime | None:
    # moov/mvhd may be at the start or the end; look in a head and tail window.
    for window in (data[:2_000_000], data[-8_000_000:]):
        index = window.find(b"mvhd")
        if index < 0:
            continue
        version = window[index + 4]
        if version == 1:
            if index + 16 > len(window):
                continue
            creation = int.from_bytes(window[index + 8 : index + 16], "big")
        else:
            if index + 12 > len(window):
                continue
            creation = int.from_bytes(window[index + 8 : index + 12], "big")
        if creation <= _MP4_EPOCH_OFFSET:
            continue
        try:
            return datetime.datetime.fromtimestamp(
                creation - _MP4_EPOCH_OFFSET, datetime.timezone.utc
            ).replace(tzinfo=None)
        except (OverflowError, OSError, ValueError):
            return None
    return None


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _from_tags(tags: dict[str, Any], source: str) -> MediaMetadata:
    taken = None
    for key in ("datetime_original", "datetime_digitized", "datetime"):
        raw = tags.get(key)
        if isinstance(raw, str):
            parsed = _parse_exif_datetime(raw)
            if parsed is not None:
                taken = parsed
                break

    return MediaMetadata(
        tags=tags,
        width=_as_int(tags.get("pixel_x_dimension")),
        height=_as_int(tags.get("pixel_y_dimension")),
        taken=taken,
        make=str(tags.get("make", "") or ""),
        model=str(tags.get("model", "") or ""),
        lens_model=str(tags.get("lens_model", "") or ""),
        iso=_as_int(tags.get("photographic_sensitivity") or tags.get("iso_speed_ratings")),
        f_number=_as_float(tags.get("f_number")),
        exposure_time=_as_float(tags.get("exposure_time")),
        focal_length=_as_float(tags.get("focal_length")),
        orientation=_as_int(tags.get("orientation")),
        source=source,
    )


def _parse_exif_datetime(value: str) -> datetime.datetime | None:
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    return None
