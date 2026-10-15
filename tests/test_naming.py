import datetime

from canon_eos_utility.metadata import MediaMetadata
from canon_eos_utility.models import CameraObject
from canon_eos_utility.naming import (
    build_context,
    render,
    render_target_path,
    sanitize_relative_path,
)


def _context() -> dict:
    camera = {
        "model": "Canon EOS R5",
        "manufacturer": "Canon",
        "serial": "0859408",
        "firmware": "3-2.2.1",
        "name": "EOSR5_859408",
    }
    obj = CameraObject(
        handle=1,
        storage_id=1,
        format=0xB108,
        size=46_312_534,
        filename="246A8454.CR3",
        capture_date="20260912T150605.0",
        width=8192,
        height=5464,
    )
    metadata = MediaMetadata(
        width=8192,
        height=5464,
        taken=datetime.datetime(2026, 9, 12, 15, 6, 5),
        make="Canon",
        model="Canon EOS R5",
        lens_model="RF24-70mm F2.8 L IS USM",
        iso=100,
        f_number=2.8,
        exposure_time=0.05,
        focal_length=56.0,
        source="cr3",
    )
    return build_context(camera, obj, metadata)


def test_render_dotted_values():
    context = _context()
    assert render("${camera.model}", context) == "Canon EOS R5"
    assert render("${original.filename}", context) == "246A8454"
    assert render("${original.extension}", context) == "CR3"
    assert (
        render("${capture.year}/${capture.month}/${capture.date}", context) == "2026/09/2026-09-12"
    )


def test_render_default_and_format():
    context = _context()
    assert render("${missing.value|none}", context) == "none"
    assert render("${capture.datetime:%Y%m%d_%H%M%S}", context) == "20260912_150605"
    assert render("${exif.iso}", context) == "100"


def test_render_unknown_is_empty():
    assert render("a${nope}b", _context()) == "ab"


def test_render_target_path_creates_subdirs():
    path = render_target_path(
        "Devices/${camera.model}/${capture.date}/${original.filename}.${original.extension}",
        _context(),
        "/base",
    )
    assert path == "/base/Devices/Canon EOS R5/2026-09-12/246A8454.CR3"


def test_render_target_path_appends_extension():
    path = render_target_path(
        "${original.filename}", _context(), "/base", original_extension=".CR3"
    )
    assert path == "/base/246A8454.CR3"


def test_sanitize_blocks_traversal():
    assert sanitize_relative_path("../../etc/passwd") == "etc/passwd"
    assert sanitize_relative_path("/absolute/path") == "absolute/path"


def test_sanitize_removes_illegal_characters():
    assert sanitize_relative_path('a<b>:"c|d?e*f') == "abcdef"


def _context_for(moment: datetime.datetime) -> dict:
    camera = {"model": "X", "manufacturer": "", "serial": "", "firmware": "", "name": ""}
    obj = CameraObject(
        handle=1, storage_id=1, format=0x3801, size=1, filename="a.jpg", capture_date=""
    )
    return build_context(camera, obj, MediaMetadata(taken=moment, source="exif"))


def test_zero_padding_control():
    context = _context_for(datetime.datetime(2026, 4, 3, 9, 5, 7))
    # Padded by default…
    assert render("${capture.month}", context) == "04"
    assert render("${capture.day}", context) == "03"
    assert render("${capture.hour}", context) == "09"
    assert render("${capture.minute}", context) == "05"
    # …but a format spec can request unpadded or explicit width.
    assert render("${capture.month:d}", context) == "4"
    assert render("${capture.day:d}", context) == "3"
    assert render("${capture.hour:d}", context) == "9"
    assert render("${capture.second:d}", context) == "7"
    assert render("${capture.day:02d}", context) == "03"
    assert render("${capture.year}", context) == "2026"


def test_week_and_weekday_variables():
    moment = datetime.datetime(2026, 9, 12, 15, 6, 5)
    context = _context_for(moment)
    iso_week = moment.isocalendar()[1]
    assert render("${capture.week}", context) == f"{iso_week:02d}"
    assert render("${capture.week:d}", context) == str(iso_week)
    assert render("${capture.weekday}", context) == str(moment.isoweekday())
    assert render("${capture.weekday_short}", context) == moment.strftime("%a")
    assert render("${capture.weekday_name}", context) == moment.strftime("%A")
