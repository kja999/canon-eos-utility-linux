"""Synthetic images for the mock camera."""

from __future__ import annotations

import io


def _pillow():
    try:
        from PIL import Image, ImageDraw  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise ImportError(
            "The mock camera needs Pillow. Install it with:\n"
            "    pip install 'canon-eos-utility[mock]'"
        ) from exc
    return Image, ImageDraw


_PALETTE = [
    (199, 74, 58),
    (58, 122, 199),
    (86, 168, 88),
    (196, 156, 52),
    (140, 90, 176),
    (46, 160, 166),
    (200, 96, 150),
    (110, 110, 120),
]


def generate_jpeg(width: int, height: int, index: int, label: str = "") -> bytes:
    """Create a colourful test JPEG."""
    Image, ImageDraw = _pillow()
    background = _PALETTE[index % len(_PALETTE)]
    image = Image.new("RGB", (width, height), background)
    draw = ImageDraw.Draw(image)

    for y in range(0, height, max(1, height // 12)):
        shade = 255 - (y * 180 // max(1, height))
        draw.line(
            [(0, y), (width, y)],
            fill=(shade, shade, shade),
            width=max(1, height // 24),
        )

    text = label or f"IMG_{index:04d}"
    draw.rectangle(
        [(width // 12, height // 2 - height // 10), (width * 11 // 12, height // 2 + height // 10)],
        fill=(0, 0, 0),
    )
    draw.text((width // 8, height // 2 - height // 14), text, fill=(255, 255, 255))

    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=85)
    return buffer.getvalue()


def generate_thumbnail(jpeg_bytes: bytes, size: tuple[int, int] = (320, 240)) -> bytes:
    Image, _ = _pillow()
    image = Image.open(io.BytesIO(jpeg_bytes))
    image.thumbnail(size)
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="JPEG", quality=80)
    return buffer.getvalue()


def jpeg_dimensions(jpeg_bytes: bytes) -> tuple[int, int]:
    Image, _ = _pillow()
    with Image.open(io.BytesIO(jpeg_bytes)) as image:
        return image.size
