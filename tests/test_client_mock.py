import pytest

from canon_eos_utility.constants import (
    LiveViewOutput,
    PropertyCode,
)
from canon_eos_utility.mock import MockCameraServer
from canon_eos_utility.models import AllowedValuesChanged, ObjectAdded, PropertyChanged
from canon_eos_utility.protocol import CameraClient


@pytest.fixture()
def server():
    srv = MockCameraServer(port=0)
    srv.start()
    try:
        yield srv
    finally:
        srv.stop()


@pytest.fixture()
def client(server):
    cam = CameraClient(host="127.0.0.1", port=server.port, client_name="Test Client")
    cam.open()
    try:
        yield cam
    finally:
        cam.disconnect()


def test_connect_returns_camera_info(client):
    assert client.connected
    assert client.info is not None
    assert "70D" in client.info.name


def test_get_device_info(client):
    info = client.get_device_info()
    assert info.manufacturer == "Canon Inc."
    assert "70D" in info.model
    assert 0x1002 in info.operations


def test_list_and_download_objects(client):
    objects = client.list_objects()
    assert len(objects) >= 1
    obj = objects[0]
    assert obj.filename.endswith(".JPG")
    assert obj.size > 0

    data = client.get_object(obj.handle)
    assert data.startswith(b"\xff\xd8\xff")
    assert len(data) == obj.size

    thumb = client.get_thumbnail(obj.handle)
    assert thumb.startswith(b"\xff\xd8\xff")


def test_partial_object(client):
    obj = client.list_objects()[0]
    head = client.get_partial_object(obj.handle, 0, 4)
    assert head == b"\xff\xd8\xff\xe0"[: len(head)]
    assert len(head) == 4


def test_initial_events_populate_properties(client):
    events = client.poll_events()
    props = {e.code: e.value for e in events if isinstance(e, PropertyChanged)}
    assert int(PropertyCode.ISO) in props
    assert int(PropertyCode.SHUTTER_SPEED) in props
    assert any(isinstance(e, AllowedValuesChanged) for e in events)


def test_set_property_emits_change_event(client):
    client.set_property(PropertyCode.ISO, 0x58)
    events = client.poll_events()
    assert PropertyChanged(code=int(PropertyCode.ISO), value=0x58) in events


def test_capture_image_adds_object(client):
    before = len(client.list_objects())
    client.capture_image()
    after = client.list_objects()
    assert len(after) == before + 1

    events = client.poll_events()
    assert any(isinstance(e, ObjectAdded) for e in events)


def test_live_view_frame(client):
    client.set_live_view_output(LiveViewOutput.CAMERA_AND_HOST)
    frame = client.get_live_view_image()
    assert frame.jpeg is not None
    assert frame.jpeg.startswith(b"\xff\xd8\xff")
    assert frame.touch_af is not None


def test_touch_af_position(client, server):
    client.set_touch_af_position(321, 123)
    assert server.state.touch_af == (321, 123)


def test_capture_destination_set_on_open(client):
    assert client.get_device_prop_value(PropertyCode.CAPTURE_DESTINATION) == b"\x02\x00\x00\x00"


def test_context_manager_opens_and_closes(server):
    with CameraClient(host="127.0.0.1", port=server.port) as camera:
        assert camera.connected
        assert camera.list_objects()
    assert not camera.connected


def test_iter_object_yields_all_bytes_in_chunks(client):
    obj = client.list_objects()[0]
    chunks = list(client.iter_object(obj.handle, obj.size, chunk_size=4096))
    assert len(chunks) > 1
    data = b"".join(chunks)
    assert len(data) == obj.size
    assert data == client.get_object(obj.handle)


def test_download_object_reports_progress(client):
    obj = client.list_objects()[0]
    seen: list[tuple[int, int]] = []
    data = client.download_object(
        obj.handle, obj.size, progress=lambda done, total: seen.append((done, total))
    )
    assert len(data) == obj.size
    assert seen[-1] == (obj.size, obj.size)


def test_set_prop_value_wire_format(server):
    """Canon SetDevicePropValueEx data is [length u32][propcode u32][value u32]."""
    import struct

    client = CameraClient(
        host="127.0.0.1", port=server.port, client_name="test", client_guid=bytes(16)
    )
    try:
        client.open()
        captured = {}
        original = client._transact

        def spy(op, params=None, data=None, **kwargs):
            captured["data"] = data
            return original(op, params=params, data=data, **kwargs)

        client._transact = spy
        client.set_property(PropertyCode.ISO, 0x58)
        assert captured["data"] == struct.pack("<III", 12, int(PropertyCode.ISO), 0x58)
    finally:
        client.disconnect()
