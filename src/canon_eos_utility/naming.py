"""Flexible file-naming templates.

Templates use ``${dotted.path}`` placeholders resolved against a context built
from the camera, the PTP object and the file's EXIF metadata, for example::

    Devices/${camera.model}/Recents/${capture.year}/${capture.month}/\\
${capture.date}/${original.filename}.${original.extension}

Placeholders may include a default (``${exif.iso|unknown}``) and a Python
format spec (``${capture.datetime:%Y%m%d_%H%M%S}``).
"""

from __future__ import annotations

import datetime
import os
import re
from collections.abc import Mapping
from typing import Any

DEFAULT_TEMPLATE = (
    "Devices/${camera.model}/Recents/"
    "${capture.year}/${capture.month}/${capture.date}/"
    "${original.filename}.${original.extension}"
)

#: Default template used for videos when a separate video template is enabled.
DEFAULT_VIDEO_TEMPLATE = (
    "Devices/${camera.model}/Videos/"
    "${capture.year}/${capture.month}/${capture.date}/"
    "${original.filename}.${original.extension}"
)

_TOKEN = re.compile(r"\$\{([^}]+)\}")
_ILLEGAL_CHARS = re.compile(r'[\x00-\x1f<>:"\\|?*]')


def resolve(context: Mapping[str, Any], path: str) -> Any:
    """Resolve a dotted ``path`` against nested mappings/objects."""
    node: Any = context
    for part in path.split("."):
        if not part:
            continue
        if isinstance(node, Mapping):
            if part not in node:
                return None
            node = node[part]
        else:
            node = getattr(node, part, None)
        if node is None:
            return None
    return node


def render(template: str, context: Mapping[str, Any], default: str = "") -> str:
    """Substitute ``${...}`` placeholders in ``template``."""

    def replace(match: re.Match[str]) -> str:
        expression = match.group(1)
        fallback = default
        if "|" in expression:
            expression, _, fallback = expression.partition("|")
        fmt = None
        if ":" in expression:
            expression, _, fmt = expression.partition(":")

        value = resolve(context, expression.strip())
        if value is None or value == "":
            value = fallback
        if fmt and value not in (None, ""):
            value = _apply_format(value, fmt)
        return "" if value is None else str(value)

    return _TOKEN.sub(replace, template)


def template_uses_exif(template: str) -> bool:
    """True if the template references any ``exif.*`` field.

    EXIF values are only known once the file has been downloaded, so for such
    templates the destination path cannot be predicted in advance.
    """
    for match in _TOKEN.finditer(template):
        expression = match.group(1)
        expression = expression.partition("|")[0].partition(":")[0].strip()
        if expression == "exif" or expression.startswith("exif."):
            return True
    return False


def _apply_format(value: Any, fmt: str) -> Any:
    if isinstance(value, (datetime.datetime, datetime.date, datetime.time)):
        try:
            return value.strftime(fmt)
        except (ValueError, TypeError):
            return value
    try:
        return format(value, fmt)
    except (ValueError, TypeError):
        return value


def sanitize_component(component: str) -> str:
    """Make a single path component safe for common filesystems."""
    cleaned = _ILLEGAL_CHARS.sub("", component)
    return cleaned.strip().strip(".")


def sanitize_relative_path(rendered: str) -> str:
    """Split on ``/`` and sanitize each component, dropping ``..`` traversal."""
    parts: list[str] = []
    for chunk in rendered.replace("\\", "/").split("/"):
        cleaned = sanitize_component(chunk)
        if cleaned and cleaned not in (".", ".."):
            parts.append(cleaned)
    return os.path.join(*parts) if parts else "download"


def render_target_path(
    template: str,
    context: Mapping[str, Any],
    base_dir: str,
    original_extension: str | None = None,
) -> str:
    """Render ``template`` into a sanitized absolute path below ``base_dir``."""
    rendered = render(template, context)
    relative = sanitize_relative_path(rendered)

    if original_extension:
        filename = os.path.basename(relative)
        if "." not in filename:
            relative = f"{relative}.{original_extension.lstrip('.')}"

    return os.path.join(base_dir, relative)


def build_context(
    camera: Mapping[str, Any],
    obj,
    metadata=None,
) -> dict[str, Any]:
    """Build the template context for a camera object and its metadata."""
    name = obj.filename or f"IMG_{obj.handle}"
    stem, dot, extension = name.rpartition(".")
    if not dot:
        stem, extension = name, ""

    taken = getattr(metadata, "taken", None) if metadata is not None else None
    if taken is None:
        from .metadata import parse_ptp_datetime

        taken = parse_ptp_datetime(getattr(obj, "capture_date", "") or "")

    return {
        "camera": dict(camera),
        "original": {
            "name": name,
            "filename": stem,
            "extension": extension,
            "stem": stem,
        },
        "capture": _capture_context(taken),
        "exif": metadata.as_context() if metadata is not None else {},
        "image": {
            "width": (getattr(metadata, "width", None) or obj.width),
            "height": (getattr(metadata, "height", None) or obj.height),
            "size": obj.size,
            "format": obj.format_name,
        },
    }


class _PaddedInt(int):
    """An int that renders zero-padded by default but honours a format spec.

    ``str(component)`` gives the zero-padded form (``03``), while
    ``f"{component:d}"`` gives the unpadded form (``3``) and
    ``f"{component:02d}"`` re-pads it.  This lets templates choose padding via
    the normal ``${path:spec}`` syntax.
    """

    def __new__(cls, value: int, width: int = 2) -> _PaddedInt:
        instance = super().__new__(cls, int(value))
        instance._width = width
        return instance

    def __str__(self) -> str:  # noqa: D105
        return f"{int(self):0{self._width}d}"

    def __format__(self, spec: str) -> str:
        return str(self) if spec == "" else format(int(self), spec)


def _capture_context(taken: datetime.datetime | None) -> dict[str, Any]:
    if taken is None:
        return {}
    iso_week = taken.isocalendar()[1]
    return {
        "datetime": taken,
        "date": taken.strftime("%Y-%m-%d"),
        "year": _PaddedInt(taken.year, 4),
        "month": _PaddedInt(taken.month, 2),
        "day": _PaddedInt(taken.day, 2),
        "hour": _PaddedInt(taken.hour, 2),
        "minute": _PaddedInt(taken.minute, 2),
        "second": _PaddedInt(taken.second, 2),
        "weekday": _PaddedInt(taken.isoweekday(), 1),  # Mon=1 … Sun=7
        "weekday_number": _PaddedInt(taken.weekday(), 1),  # Mon=0 … Sun=6
        "weekday_short": taken.strftime("%a"),  # Mon
        "weekday_name": taken.strftime("%A"),  # Monday
        "week": _PaddedInt(iso_week, 2),  # ISO week 01–53
        "time": taken.strftime("%H:%M:%S"),
        "epoch": int(taken.timestamp()),
    }


#: Variables shown in the settings dialog's reference list.
AVAILABLE_VARIABLES: tuple[tuple[str, str], ...] = (
    ("camera.model", "Camera model name (e.g. Canon EOS R5)"),
    ("camera.manufacturer", "Camera manufacturer"),
    ("camera.serial", "Camera serial number"),
    ("camera.firmware", "Camera firmware version"),
    ("original.name", "Original filename with extension"),
    ("original.filename", "Original filename without extension"),
    ("original.extension", "Original extension (e.g. CR3)"),
    ("capture.date", "Capture date (YYYY-MM-DD)"),
    ("capture.year", "Capture year"),
    ("capture.month", "Capture month (01-12; add :d for unpadded)"),
    ("capture.day", "Capture day (01-31; add :d for unpadded)"),
    ("capture.week", "ISO week number (01-53; add :d for unpadded)"),
    ("capture.weekday", "ISO weekday number (Mon=1 … Sun=7)"),
    ("capture.weekday_short", "Short weekday name (Mon)"),
    ("capture.weekday_name", "Weekday name (Monday)"),
    ("capture.time", "Capture time (HH:MM:SS)"),
    ("capture.hour", "Hour (00-23; add :d for unpadded)"),
    ("capture.minute", "Minute (00-59; add :d for unpadded)"),
    ("capture.second", "Second (00-59; add :d for unpadded)"),
    ("capture.datetime", "Capture datetime (supports :%format)"),
    ("exif.iso", "ISO speed"),
    ("exif.f_number", "Aperture f-number"),
    ("exif.exposure_time", "Exposure time in seconds"),
    ("exif.focal_length", "Focal length"),
    ("exif.lens_model", "Lens model"),
    ("image.width", "Image width in pixels"),
    ("image.height", "Image height in pixels"),
    ("image.format", "Image format (e.g. CR3 raw)"),
)
