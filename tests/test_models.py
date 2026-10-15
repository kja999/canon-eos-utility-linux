from canon_eos_utility.constants import ObjectFormat
from canon_eos_utility.models import CameraObject


def _obj(fmt, filename):
    return CameraObject(handle=1, storage_id=1, format=int(fmt), size=10, filename=filename)


def test_cr3_is_image_from_format_code():
    assert _obj(ObjectFormat.CR3, "IMG_0001.CR3").is_image
    assert not _obj(ObjectFormat.CR3, "IMG_0001.CR3").is_movie


def test_raw_movie_format_codes():
    assert _obj(ObjectFormat.MOV, "MVI_0001.MOV").is_movie
    assert _obj(ObjectFormat.MP4, "MVI_0001.MP4").is_movie


def test_extension_fallback_for_unknown_format():
    unknown = _obj(0xDEAD, "SHOT.CR3")
    assert unknown.is_image
    assert _obj(0xDEAD, "CLIP.MP4").is_movie
    assert not _obj(0xDEAD, "MYSTERY.BIN").is_image


def test_folder_detection():
    assert _obj(ObjectFormat.ASSOCIATION, "DCIM").is_folder


def test_capture_date_display():
    obj = _obj(ObjectFormat.CR3, "IMG.CR3")
    obj.capture_date = "20260723T113741.0"
    assert obj.capture_date_display == "2026-07-23 11:37:41"
    obj.capture_date = ""
    assert obj.capture_date_display == ""
