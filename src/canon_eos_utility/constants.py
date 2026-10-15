"""PTP/IP protocol constants for Canon EOS cameras.

Values are gathered from the CIPA PTP/IP specification draft (DC-X005), the
gPhoto PTP/IP notes, Julian Schroden's "Exploring the PTP/IP Protocol" article
series and the reference implementations ``mmattes/ptpip`` (Python) and
``JulianSchroden/cine_remote`` (Dart).
"""

from __future__ import annotations

from enum import IntEnum


class PacketType(IntEnum):
    """PTP/IP packet types (the second UINT32 of every packet)."""

    INIT_COMMAND_REQUEST = 0x0001
    INIT_COMMAND_ACK = 0x0002
    INIT_EVENT_REQUEST = 0x0003
    INIT_EVENT_ACK = 0x0004
    INIT_FAIL = 0x0005
    OPERATION_REQUEST = 0x0006
    OPERATION_RESPONSE = 0x0007
    EVENT = 0x0008
    START_DATA = 0x0009
    DATA = 0x000A
    CANCEL = 0x000B
    END_DATA = 0x000C
    PING = 0x000D
    PONG = 0x000E


class DataPhase(IntEnum):
    """DataPhaseInfo field of an operation request."""

    NO_DATA = 0x00000001
    WITH_DATA = 0x00000002
    DATA_IN = 0x00000003


class ResponseCode(IntEnum):
    """PTP operation response codes."""

    UNDEFINED = 0x2000
    OK = 0x2001
    GENERAL_ERROR = 0x2002
    SESSION_NOT_OPEN = 0x2003
    INVALID_TRANSACTION_ID = 0x2004
    OPERATION_NOT_SUPPORTED = 0x2005
    PARAMETER_NOT_SUPPORTED = 0x2006
    INCOMPLETE_TRANSFER = 0x2007
    INVALID_STORAGE_ID = 0x2008
    INVALID_OBJECT_HANDLE = 0x2009
    DEVICE_PROP_NOT_SUPPORTED = 0x200A
    INVALID_OBJECT_FORMAT_CODE = 0x200B
    STORE_FULL = 0x200C
    OBJECT_WRITE_PROTECTED = 0x200D
    STORE_READ_ONLY = 0x200E
    ACCESS_DENIED = 0x200F
    NO_THUMBNAIL_PRESENT = 0x2010
    SELF_TEST_FAILED = 0x2011
    PARTIAL_DELETION = 0x2012
    STORE_NOT_AVAILABLE = 0x2013
    SPECIFICATION_BY_FORMAT_UNSUPPORTED = 0x2014
    NO_VALID_OBJECT_INFO = 0x2015
    INVALID_CODE_FORMAT = 0x2016
    UNKNOWN_VENDOR_CODE = 0x2017
    CAPTURE_ALREADY_TERMINATED = 0x2018
    DEVICE_BUSY = 0x2019
    INVALID_PARENT_OBJECT = 0x201A
    INVALID_DEVICE_PROP_FORMAT = 0x201B
    INVALID_DEVICE_PROP_VALUE = 0x201C
    INVALID_PARAMETER = 0x201D
    SESSION_ALREADY_OPEN = 0x201E
    TRANSACTION_CANCELLED = 0x201F
    SPECIFICATION_OF_DESTINATION_UNSUPPORTED = 0x2020


class OperationCode(IntEnum):
    """PTP operation codes (standard + Canon vendor extensions)."""

    # Standard PTP
    GET_DEVICE_INFO = 0x1001
    OPEN_SESSION = 0x1002
    CLOSE_SESSION = 0x1003
    GET_STORAGE_IDS = 0x1004
    GET_STORAGE_INFO = 0x1005
    GET_NUM_OBJECTS = 0x1006
    GET_OBJECT_HANDLES = 0x1007
    GET_OBJECT_INFO = 0x1008
    GET_OBJECT = 0x1009
    GET_THUMB = 0x100A
    DELETE_OBJECT = 0x100B
    SEND_OBJECT_INFO = 0x100C
    SEND_OBJECT = 0x100D
    INITIATE_CAPTURE = 0x100E
    FORMAT_STORE = 0x100F
    GET_DEVICE_PROP_DESC = 0x1014
    GET_DEVICE_PROP_VALUE = 0x1015
    SET_DEVICE_PROP_VALUE = 0x1016
    GET_PARTIAL_OBJECT = 0x101B

    # Canon EOS vendor extensions
    SET_PROP_VALUE = 0x9110
    SET_REMOTE_MODE = 0x9114
    SET_EVENT_MODE = 0x9115
    GET_EVENT_DATA = 0x9116
    KEEP_DEVICE_ON = 0x911D
    START_IMAGE_CAPTURE = 0x9128
    STOP_IMAGE_CAPTURE = 0x9129
    GET_LIVE_VIEW_IMAGE = 0x9153
    SET_TOUCH_AF_POSITION = 0x915B


class EventCode(IntEnum):
    """PTP event codes reported through the Canon ``GetEventData`` operation."""

    CANCEL_TRANSACTION = 0x4001
    OBJECT_ADDED = 0x4002
    OBJECT_REMOVED = 0x4003
    STORE_ADDED = 0x4004
    STORE_REMOVED = 0x4005
    DEVICE_PROP_CHANGED = 0x4006
    OBJECT_INFO_CHANGED = 0x4007
    DEVICE_INFO_CHANGED = 0x4008
    REQUEST_OBJECT_TRANSFER = 0x4009
    STORE_FULL = 0x400A
    STORAGE_INFO_CHANGED = 0x400C
    CAPTURE_COMPLETE = 0x400D

    # Canon specific
    OBJECT_ADDED_IN_SDRAM = 0xC101
    CAPTURE_COMPLETE_REC_IN_SDRAM = 0xC102
    RECORDING_INTERRUPTED = 0xC105
    PROPERTY_CHANGED = 0xC189
    ALLOWED_VALUES_CHANGED = 0xC18A


class PropertyCode(IntEnum):
    """Canon EOS vendor property codes."""

    APERTURE = 0xD101
    SHUTTER_SPEED = 0xD102
    ISO = 0xD103
    WHITE_BALANCE = 0xD10A
    CAPTURE_DESTINATION = 0xD11C
    LIVE_VIEW_OUTPUT = 0xD1B0
    #: Electronic viewfinder mode; must be 1 before live view will start.
    EVF_MODE = 0xD1B1


class CapturePhase(IntEnum):
    FOCUS = 0x01
    RELEASE = 0x02


class RemoteMode(IntEnum):
    DISABLED = 0x00
    ENABLED = 0x01


class EventMode(IntEnum):
    DISABLED = 0x00
    ENABLED = 0x01


class LiveViewOutput(IntEnum):
    NONE = 0x00
    CAMERA = 0x01
    HOST = 0x02
    CAMERA_AND_HOST = 0x03


class CaptureDestination(IntEnum):
    STORAGE1 = 0x01
    STORAGE2 = 0x02
    HOST = 0x04
    HOST_AND_CAMERA = 0x06


class ObjectFormat(IntEnum):
    """Common PTP object format codes."""

    UNDEFINED = 0x3000
    ASSOCIATION = 0x3001
    SCRIPT = 0x3002
    EXECUTABLE = 0x3003
    TEXT = 0x3004
    HTML = 0x3005
    DPOF = 0x3006
    AIFF = 0x3007
    WAV = 0x3008
    MP3 = 0x3009
    AVI = 0x300A
    MPEG = 0x300B
    ASF = 0x300C
    EXIF_JPEG = 0x3801
    TIFF_EP = 0x3802
    FLASHPIX = 0x3803
    BMP = 0x3804
    CIFF = 0x3805
    UNDEFINED_IMAGE = 0x3806
    GIF = 0x3807
    JFIF = 0x3808
    PCD = 0x3809
    PICT = 0x380A
    PNG = 0x380B
    TIFF = 0x380D
    JP2 = 0x380F
    JPEG = 0x3810
    DNG = 0x3811
    # Canon vendor object format codes (see libgphoto2 camlibs/ptp2/ptp.h).
    CRW = 0xB101
    CR2 = 0xB103
    MOV = 0xB104
    MOV2 = 0xB105
    CR3 = 0xB108
    CHDK_CRW = 0xB1FF
    MP4 = 0xB982


#: Human readable names for object formats we care about.
OBJECT_FORMAT_NAMES: dict[int, str] = {
    ObjectFormat.EXIF_JPEG: "JPEG",
    ObjectFormat.JFIF: "JPEG",
    ObjectFormat.JPEG: "JPEG",
    ObjectFormat.PNG: "PNG",
    ObjectFormat.DNG: "DNG raw",
    ObjectFormat.TIFF: "TIFF",
    ObjectFormat.TIFF_EP: "TIFF",
    ObjectFormat.CRW: "CRW raw",
    ObjectFormat.CR2: "CR2 raw",
    ObjectFormat.CR3: "CR3 raw",
    ObjectFormat.MOV: "MOV movie",
    ObjectFormat.MOV2: "MOV movie",
    ObjectFormat.MP4: "MP4 movie",
    ObjectFormat.AVI: "AVI movie",
}


#: Property codes that represent camera settings we expose as controls.
CONTROL_PROPERTIES: tuple[int, ...] = (
    PropertyCode.APERTURE,
    PropertyCode.SHUTTER_SPEED,
    PropertyCode.ISO,
    PropertyCode.WHITE_BALANCE,
)

PROPERTY_NAMES: dict[int, str] = {
    PropertyCode.APERTURE: "Aperture",
    PropertyCode.SHUTTER_SPEED: "Shutter speed",
    PropertyCode.ISO: "ISO",
    PropertyCode.WHITE_BALANCE: "White balance",
    PropertyCode.CAPTURE_DESTINATION: "Capture destination",
    PropertyCode.LIVE_VIEW_OUTPUT: "Live view output",
}


# ---------------------------------------------------------------------------
# Property value mappings (native code -> display label)
# ---------------------------------------------------------------------------

#: ``(native, label)`` pairs for the aperture property (0xD101).
APERTURE_VALUES: tuple[tuple[int, str], ...] = (
    (0x15, "f/1.8"),
    (0x18, "f/2.0"),
    (0x1B, "f/2.2"),
    (0x1D, "f/2.5"),
    (0x20, "f/2.8"),
    (0x23, "f/3.2"),
    (0x25, "f/3.5"),
    (0x28, "f/4.0"),
    (0x2B, "f/4.5"),
    (0x2D, "f/5.0"),
    (0x30, "f/5.6"),
    (0x33, "f/6.3"),
    (0x35, "f/7.1"),
    (0x38, "f/8.0"),
    (0x3B, "f/9.0"),
    (0x3D, "f/10"),
    (0x40, "f/11"),
    (0x43, "f/13"),
    (0x45, "f/14"),
    (0x48, "f/16"),
)

#: ``(native, label)`` pairs for the shutter speed property (0xD102).
SHUTTER_SPEED_VALUES: tuple[tuple[int, str], ...] = (
    (0x10, "30s"),
    (0x13, "25s"),
    (0x15, "20s"),
    (0x18, "15s"),
    (0x1B, "13s"),
    (0x1D, "10s"),
    (0x20, "8s"),
    (0x23, "6s"),
    (0x25, "5s"),
    (0x28, "4s"),
    (0x2B, "3.2s"),
    (0x2D, "2.5s"),
    (0x30, "2s"),
    (0x33, "1.6s"),
    (0x35, "1.3s"),
    (0x38, "1s"),
    (0x3B, "0.8s"),
    (0x3D, "0.6s"),
    (0x40, "0.5s"),
    (0x43, "0.4s"),
    (0x45, "0.3s"),
    (0x48, "1/4"),
    (0x4B, "1/5"),
    (0x4D, "1/6"),
    (0x50, "1/8"),
    (0x53, "1/10"),
    (0x55, "1/13"),
    (0x58, "1/15"),
    (0x5B, "1/20"),
    (0x5D, "1/25"),
    (0x60, "1/30"),
    (0x63, "1/40"),
    (0x65, "1/50"),
    (0x68, "1/60"),
    (0x6B, "1/80"),
    (0x6D, "1/100"),
    (0x70, "1/125"),
    (0x73, "1/160"),
    (0x75, "1/200"),
    (0x78, "1/250"),
    (0x7B, "1/320"),
    (0x7D, "1/400"),
    (0x80, "1/500"),
    (0x83, "1/640"),
    (0x85, "1/800"),
    (0x88, "1/1000"),
    (0x8B, "1/1250"),
    (0x8D, "1/1600"),
    (0x90, "1/2000"),
    (0x93, "1/2500"),
    (0x95, "1/3200"),
    (0x98, "1/4000"),
    (0x9B, "1/5000"),
    (0x9D, "1/6400"),
    (0xA0, "1/8000"),
)

#: ``(native, label)`` pairs for the ISO property (0xD103).
ISO_VALUES: tuple[tuple[int, str], ...] = (
    (0x00, "Auto"),
    (0x48, "100"),
    (0x4B, "125"),
    (0x4D, "160"),
    (0x50, "200"),
    (0x53, "250"),
    (0x55, "320"),
    (0x58, "400"),
    (0x5B, "500"),
    (0x5D, "640"),
    (0x60, "800"),
    (0x63, "1000"),
    (0x65, "1250"),
    (0x68, "1600"),
    (0x6B, "2000"),
    (0x6D, "2500"),
    (0x70, "3200"),
    (0x73, "4000"),
    (0x75, "5000"),
    (0x78, "6400"),
    (0x7B, "8000"),
    (0x7D, "10000"),
    (0x80, "12800"),
)

VALUE_MAPS: dict[int, tuple[tuple[int, str], ...]] = {
    PropertyCode.APERTURE: APERTURE_VALUES,
    PropertyCode.SHUTTER_SPEED: SHUTTER_SPEED_VALUES,
    PropertyCode.ISO: ISO_VALUES,
}

#: Canon EOS white balance modes, as documented by libgphoto2 / EDSDK.  Some
#: bodies (e.g. the EOS R5) instead report the white balance as a colour
#: temperature in Kelvin, which is shown as ``<n>K``.
WHITE_BALANCE_VALUES: tuple[tuple[int, str], ...] = (
    (0x00, "Auto (Ambience)"),
    (0x01, "Daylight"),
    (0x02, "Cloudy"),
    (0x03, "Tungsten"),
    (0x04, "White fluorescent"),
    (0x05, "Flash"),
    (0x06, "Custom"),
    (0x08, "Shade"),
    (0x09, "Colour temperature"),
    (0x0A, "Custom 1"),
    (0x0B, "Custom 2"),
    (0x0C, "Custom 3"),
    (0x0F, "Manual 2"),
    (0x10, "Manual 3"),
    (0x12, "Manual 4"),
    (0x13, "Manual 5"),
    (0x14, "Custom 4"),
    (0x15, "Custom 5"),
    (0x17, "Auto (White priority)"),
)

_WB_LOOKUP: dict[int, str] = dict(WHITE_BALANCE_VALUES)

_VALUE_LOOKUP: dict[int, dict[int, str]] = {code: dict(pairs) for code, pairs in VALUE_MAPS.items()}
_VALUE_REVERSE: dict[int, dict[str, int]] = {
    code: {label: native for native, label in pairs} for code, pairs in VALUE_MAPS.items()
}


def property_value_label(prop_code: int, value: int) -> str:
    """Return a human readable label for a property value.

    Falls back to a hexadecimal representation for unknown values.
    """

    code = int(prop_code)
    native = int(value)
    lookup = _VALUE_LOOKUP.get(code)
    if lookup is not None and native in lookup:
        return lookup[native]
    if code == int(PropertyCode.WHITE_BALANCE):
        if native in _WB_LOOKUP:
            return _WB_LOOKUP[native]
        if 1000 <= native <= 20000:
            return f"{native}K"
    return f"0x{native:02X}"


def property_value_from_label(prop_code: int, label: str) -> int | None:
    """Inverse of :func:`property_value_label` (label -> native value)."""

    reverse = _VALUE_REVERSE.get(int(prop_code), {})
    if label in reverse:
        return reverse[label]
    if label.endswith("K") and label[:-1].isdigit():
        return int(label[:-1])
    return None


# PTP default port used for both the command and event channel.
PTPIP_PORT = 15740

# SSDP / UPnP discovery constants.
SSDP_MULTICAST_ADDR = "239.255.255.250"
SSDP_PORT = 1900
CANON_SERVICE_TYPE = "urn:schemas-canon-com:service:ICPO-WFTEOSSystemService:1"
