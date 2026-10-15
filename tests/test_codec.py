from canon_eos_utility.constants import (
    EventCode,
    ObjectFormat,
    PropertyCode,
    property_value_from_label,
    property_value_label,
)
from canon_eos_utility.models import (
    AllowedValuesChanged,
    CameraObject,
    DeviceInfo,
    ObjectAdded,
    PropertyChanged,
    StorageInfo,
)
from canon_eos_utility.protocol.codec import (
    encode_device_info,
    encode_event_data,
    encode_object_info,
    encode_storage_info,
    extract_jpeg,
    parse_device_info,
    parse_event_data,
    parse_live_view,
    parse_object_info,
    parse_storage_info,
)


def test_property_value_labels():
    assert property_value_label(PropertyCode.ISO, 0x50) == "200"
    assert property_value_label(PropertyCode.SHUTTER_SPEED, 0x70) == "1/125"
    assert property_value_label(PropertyCode.APERTURE, 0x30) == "f/5.6"
    assert property_value_label(PropertyCode.ISO, 0xFFFF) == "0xFFFF"


def test_property_value_reverse_lookup():
    assert property_value_from_label(PropertyCode.ISO, "200") == 0x50
    assert property_value_from_label(PropertyCode.SHUTTER_SPEED, "1/125") == 0x70


def test_object_info_roundtrip():
    obj = CameraObject(
        handle=0,
        storage_id=0x1234,
        format=int(ObjectFormat.EXIF_JPEG),
        size=123456,
        filename="IMG_0001.JPG",
        capture_date="2026-10-13 12:00:00",
        width=1600,
        height=1067,
    )
    parsed = parse_object_info(encode_object_info(obj, thumb=b"thumb"))
    assert parsed.filename == "IMG_0001.JPG"
    assert parsed.size == 123456
    assert parsed.width == 1600
    assert parsed.height == 1067
    assert parsed.format == int(ObjectFormat.EXIF_JPEG)


def test_device_info_roundtrip():
    info = DeviceInfo(
        standard_version=100,
        operations=[0x1001, 0x1002],
        events=[0xC189],
        properties=[0xD103],
        manufacturer="Canon Inc.",
        model="EOS 70D",
        device_version="3.1.0",
        serial_number="1234",
    )
    parsed = parse_device_info(encode_device_info(info))
    assert parsed.model == "EOS 70D"
    assert parsed.operations == [0x1001, 0x1002]
    assert parsed.properties == [0xD103]
    assert parsed.serial_number == "1234"


def test_storage_info_roundtrip():
    info = StorageInfo(
        storage_id=0,
        max_capacity=64 * 1024**3,
        free_space=57 * 1024**3,
        max_objects=9999,
        free_objects=9000,
        description="Memory card",
    )
    parsed = parse_storage_info(encode_storage_info(info))
    assert parsed.description == "Memory card"
    assert parsed.max_capacity == 64 * 1024**3


def test_event_data_roundtrip():
    events = [
        PropertyChanged(code=int(PropertyCode.ISO), value=0x58),
        AllowedValuesChanged(code=int(PropertyCode.APERTURE), values=[0x15, 0x18]),
        ObjectAdded(handle=42),
    ]
    parsed = parse_event_data(encode_event_data(events))
    assert PropertyChanged(code=int(PropertyCode.ISO), value=0x58) in parsed
    allowed = next(e for e in parsed if isinstance(e, AllowedValuesChanged))
    assert allowed.values == [0x15, 0x18]
    assert ObjectAdded(handle=42) in parsed


def test_event_code_values():
    assert int(EventCode.PROPERTY_CHANGED) == 0xC189
    assert int(EventCode.ALLOWED_VALUES_CHANGED) == 0xC18A


def test_extract_jpeg():
    payload = b"\x00\x01" + b"\xff\xd8\xff" + b"data" + b"\xff\xd9" + b"\x99"
    assert extract_jpeg(payload) == b"\xff\xd8\xffdata\xff\xd9"
    assert extract_jpeg(b"no jpeg here") is None


def test_parse_live_view_with_touch_af():
    from canon_eos_utility.protocol.packets import ByteWriter

    jpeg = b"\xff\xd8\xff" + b"payload" + b"\xff\xd9"
    w = ByteWriter()
    w.u32(4 + 4 + len(jpeg)).u32(0x1).raw(jpeg)
    w.u32(4 + 4 + 24).u32(0x8)
    w.u32(0x30).u32(0x1).u32(100).u32(200).u32(160).u32(120)

    frame = parse_live_view(w.build())
    assert frame.jpeg == jpeg
    assert frame.touch_af is not None
    assert (frame.touch_af.x, frame.touch_af.y) == (100, 200)


def test_unknown_property_label_falls_back_to_hex():
    assert property_value_label(0xDEAD, 0x1F) == "0x1F"


def test_white_balance_enum_and_kelvin_labels():
    from canon_eos_utility.constants import property_value_from_label

    # DSLR-style enum (libgphoto2 / EDSDK)
    assert property_value_label(PropertyCode.WHITE_BALANCE, 0x01) == "Daylight"
    assert property_value_label(PropertyCode.WHITE_BALANCE, 0x00) == "Auto (Ambience)"
    # EOS R5 reports colour temperature in Kelvin (Daylight = 5200K)
    assert property_value_label(PropertyCode.WHITE_BALANCE, 5200) == "5200K"
    assert property_value_label(PropertyCode.WHITE_BALANCE, 0x1E14) == "7700K"
    assert property_value_from_label(PropertyCode.WHITE_BALANCE, "5200K") == 5200
