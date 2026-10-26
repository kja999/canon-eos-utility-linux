import datetime

from canon_eos_utility.metadata import parse_ptp_datetime, read_metadata


def test_parse_ptp_datetime():
    assert parse_ptp_datetime("20260912T150605.0") == datetime.datetime(2026, 9, 12, 15, 6, 5)
    assert parse_ptp_datetime("") is None
    assert parse_ptp_datetime("garbage") is None


def _write_jpeg_with_exif(path) -> None:
    from PIL import Image

    image = Image.new("RGB", (10, 10), (120, 30, 30))
    exif = image.getexif()
    exif[0x010F] = "Canon"
    exif[0x0110] = "Canon EOS R5"
    exif[0x0132] = "2026:09:12 15:06:05"
    image.save(path, "JPEG", exif=exif)


def test_read_jpeg_exif(tmp_path):
    path = tmp_path / "a.jpg"
    _write_jpeg_with_exif(str(path))

    metadata = read_metadata(str(path))
    assert metadata.model == "Canon EOS R5"
    assert metadata.make == "Canon"
    assert metadata.taken == datetime.datetime(2026, 9, 12, 15, 6, 5)
    assert metadata.source == "exif"


def test_read_jpeg_without_exif_uses_fallback(tmp_path):
    from PIL import Image

    path = tmp_path / "b.jpg"
    Image.new("RGB", (10, 10)).save(str(path), "JPEG")

    metadata = read_metadata(
        str(path),
        fallback_datetime=datetime.datetime(2020, 1, 2, 3, 4, 5),
        fallback_size=(640, 480),
    )
    assert metadata.taken == datetime.datetime(2020, 1, 2, 3, 4, 5)
    assert (metadata.width, metadata.height) == (640, 480)


def test_read_cr3_extracts_cmt_boxes(tmp_path):
    from PIL import Image

    tiff_path = tmp_path / "tiff"
    image = Image.new("RGB", (10, 10))
    exif = image.getexif()
    exif[0x0110] = "Canon EOS R5"
    exif[0x0132] = "2026:09:12 15:06:05"
    image.save(str(tiff_path), "TIFF", exif=exif)
    tiff = tiff_path.read_bytes()

    box = (len(tiff) + 8).to_bytes(4, "big") + b"CMT1" + tiff
    container = b"\x00\x00\x00\x18ftypcrx " + box
    cr3 = tmp_path / "a.CR3"
    cr3.write_bytes(container)

    metadata = read_metadata(str(cr3))
    assert metadata.source == "cr3"
    assert metadata.model == "Canon EOS R5"
    assert metadata.taken == datetime.datetime(2026, 9, 12, 15, 6, 5)


def test_read_mp4_creation_time(tmp_path):
    epoch = 1_700_000_000 + 2_082_844_800
    body = (
        b"\x00\x00\x00\x00"
        + epoch.to_bytes(4, "big")
        + (1000).to_bytes(4, "big")
        + (0).to_bytes(4, "big")
    )
    box = (len(body) + 8).to_bytes(4, "big") + b"mvhd" + body
    data = b"\x00\x00\x00\x10ftypisom" + box

    movie = tmp_path / "clip.MP4"
    movie.write_bytes(data)

    metadata = read_metadata(str(movie))
    assert metadata.source == "mp4"
    assert metadata.taken == datetime.datetime(2023, 11, 14, 22, 13, 20)


def _large_tiff(size: int) -> bytes:
    """TIFF block whose payload exceeds the 64 KiB EXIF APP1 limit."""
    import io

    from PIL import Image

    image = Image.new("RGB", (10, 10), (120, 30, 30))
    exif = image.getexif()
    exif[0x0110] = "Canon EOS R5"
    buffer = io.BytesIO()
    image.save(buffer, "TIFF", exif=exif)
    tiff = buffer.getvalue()
    assert len(tiff) < size
    return tiff + b"\x00" * (size - len(tiff))


def test_wrap_tiff_as_app1_truncates_oversized_tiff():
    """Regression: a >64 KiB TIFF used to overflow the 16-bit APP1 length."""
    import struct

    from canon_eos_utility.metadata import _EXIF_HEADER, _wrap_tiff_as_app1

    tiff = _large_tiff(200_000)
    segment = _wrap_tiff_as_app1(tiff)

    assert segment[:2] == b"\xff\xe1"
    (length,) = struct.unpack(">H", segment[2:4])
    assert length <= 0xFFFF
    assert length == len(segment) - 4 - 2  # marker + length + trailing EOI
    # The IFDs live at the front, so the head of the TIFF is kept verbatim.
    assert segment[4 : 4 + len(_EXIF_HEADER)] == _EXIF_HEADER
    assert segment[4 + len(_EXIF_HEADER) : -2] == tiff[: length - len(_EXIF_HEADER)]
    assert segment.endswith(b"\xff\xd9")


def test_read_tags_from_oversized_tiff_block():
    """Truncation must not stop the tags at the head of the block being read."""
    from canon_eos_utility.metadata import _read_wrapped_tags

    tags = _read_wrapped_tags(_large_tiff(200_000))
    assert "Canon EOS R5" in tags.values()
