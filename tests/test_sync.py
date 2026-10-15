import os

from canon_eos_utility.config import AppConfig
from canon_eos_utility.mock import MockCameraServer
from canon_eos_utility.models import CameraObject
from canon_eos_utility.protocol import CameraClient
from canon_eos_utility.sync import (
    CameraSync,
    SyncState,
    output_for,
    partial_path,
    unique_target,
)


def test_unique_target(tmp_path):
    existing = tmp_path / "a.txt"
    existing.write_text("x")
    result = unique_target(str(existing))
    assert result.endswith("a (1).txt")


def test_partial_path_uses_staging_dir(tmp_path):
    part = partial_path(str(tmp_path), "IMG_0001.JPG")
    assert part.endswith(os.path.join(".canon-eos-partial", "IMG_0001.JPG.part"))
    assert os.path.isdir(os.path.dirname(part))


def test_sync_state_roundtrip(tmp_path):
    obj = CameraObject(handle=1, storage_id=1, format=0x3801, size=10, filename="a.jpg")
    state = SyncState(str(tmp_path / "state.json"))
    assert not state.seen(obj)

    state.mark(obj, str(tmp_path / "a.jpg"))
    (tmp_path / "a.jpg").write_bytes(b"x" * 10)
    assert state.seen(obj)

    state.save()
    reloaded = SyncState(str(tmp_path / "state.json"))
    assert reloaded.seen(obj)


def test_camera_sync_downloads_and_skips(tmp_path):
    server = MockCameraServer(port=0)
    server.start()
    client = CameraClient(
        host="127.0.0.1", port=server.port, client_name="test", client_guid=bytes(16)
    )
    try:
        client.open()
        device = client.get_device_info()
        context = {
            "model": device.model,
            "manufacturer": device.manufacturer,
            "serial": device.serial_number,
            "firmware": device.device_version,
            "name": client.info.name,
        }
        config = AppConfig(filename_template="${original.name}", download_directory=str(tmp_path))
        sync = CameraSync(client, config, context)
        state = SyncState(str(tmp_path / "state.json"))

        downloaded, skipped, failed = sync.sync_all(state=state)
        assert (downloaded, skipped, failed) == (4, 0, 0)
        assert len(list(tmp_path.glob("IMG_*.JPG"))) == 4

        # A second pass must not re-download anything.
        downloaded, skipped, failed = sync.sync_all(state=state)
        assert (downloaded, skipped, failed) == (0, 4, 0)
    finally:
        client.disconnect()
        server.stop()


def test_output_for_routes_videos_separately(tmp_path):
    photo_dir = tmp_path / "photos"
    video_dir = tmp_path / "videos"
    config = AppConfig(
        download_directory=str(photo_dir),
        filename_template="P/${original.name}",
        use_video_template=True,
        video_download_directory=str(video_dir),
        video_filename_template="V/${original.name}",
    )
    photo = CameraObject(handle=1, storage_id=1, format=0x3801, size=1, filename="a.jpg")
    movie = CameraObject(handle=2, storage_id=1, format=0xB982, size=1, filename="m.mp4")

    assert output_for(photo, config) == (str(photo_dir), "P/${original.name}")
    assert output_for(movie, config) == (str(video_dir), "V/${original.name}")

    # With the option disabled, videos use the photo folder/template.
    config.use_video_template = False
    directory, template = output_for(movie, config)
    assert directory == str(photo_dir)
    assert template == "P/${original.name}"


def test_camera_sync_routes_movies(tmp_path):
    """Movies (non-image objects) go to the video folder when enabled."""
    server = MockCameraServer(port=0)
    server.start()
    client = CameraClient(
        host="127.0.0.1", port=server.port, client_name="test", client_guid=bytes(16)
    )
    try:
        client.open()
        context = {
            "model": "Mock",
            "manufacturer": "",
            "serial": "",
            "firmware": "",
            "name": "Mock",
        }
        config = AppConfig(
            download_directory=str(tmp_path / "photos"),
            filename_template="${original.name}",
            use_video_template=True,
            video_download_directory=str(tmp_path / "videos"),
            video_filename_template="${original.name}",
        )
        sync = CameraSync(client, config, context)

        # Reclassify one mock object as a movie to exercise the routing.
        objects = sync.media_objects()
        objects[0].format = 0xB982  # MP4
        objects[0].filename = "CLIP.MP4"

        target = sync.download(objects[0])
        assert target.startswith(str(tmp_path / "videos"))
    finally:
        client.disconnect()
        server.stop()


def test_finalize_sets_file_times_to_capture_date(tmp_path):
    import datetime
    import os

    from PIL import Image

    from canon_eos_utility.sync import finalize_download

    image = Image.new("RGB", (8, 8))
    exif = image.getexif()
    exif[0x0132] = "2021:03:04 05:06:07"  # DateTime
    source = tmp_path / "src.jpg"
    image.save(str(source), "JPEG", exif=exif)

    obj = CameraObject(
        handle=1,
        storage_id=1,
        format=0x3801,
        size=source.stat().st_size,
        filename="a.jpg",
    )
    part = tmp_path / "a.jpg.part"
    part.write_bytes(source.read_bytes())

    target = finalize_download(obj, str(tmp_path / "out"), str(part), "${original.name}", {})
    expected = datetime.datetime(2021, 3, 4, 5, 6, 7).timestamp()
    assert abs(os.path.getmtime(target) - expected) < 1
    assert abs(os.path.getatime(target) - expected) < 1


def test_finalize_can_leave_file_times_untouched(tmp_path):
    import datetime
    import os
    import time

    from canon_eos_utility.sync import finalize_download

    obj = CameraObject(
        handle=1,
        storage_id=1,
        format=0x3801,
        size=3,
        filename="b.jpg",
        capture_date="20100101T000000.0",
    )
    part = tmp_path / "b.jpg.part"
    part.write_bytes(b"\xff\xd8\xff\xd9")

    target = finalize_download(
        obj, str(tmp_path / "out"), str(part), "${original.name}", {}, set_times=False
    )
    # Not set to the 2010 capture date; it is "now".
    assert os.path.getmtime(target) > datetime.datetime(2020, 1, 1).timestamp()
    assert abs(os.path.getmtime(target) - time.time()) < 60


def test_resolve_target_policies(tmp_path):
    from canon_eos_utility.sync import (
        POLICY_ASK,
        POLICY_OVERWRITE,
        POLICY_RENAME,
        POLICY_SKIP,
        resolve_target,
    )

    target = tmp_path / "a.jpg"
    target.write_bytes(b"x")

    assert resolve_target(str(target), POLICY_OVERWRITE) == str(target)
    assert resolve_target(str(target), POLICY_SKIP) is None
    assert resolve_target(str(target), POLICY_RENAME) == str(tmp_path / "a (1).jpg")
    assert resolve_target(str(target), POLICY_ASK, ask=lambda _t: POLICY_SKIP) is None
    assert resolve_target(str(target), POLICY_ASK, ask=lambda _t: POLICY_OVERWRITE) == str(target)
    # A non-existing target is always returned unchanged.
    assert resolve_target(str(tmp_path / "new.jpg"), POLICY_SKIP) == str(tmp_path / "new.jpg")


def test_finalize_skip_and_overwrite(tmp_path):
    from canon_eos_utility.sync import (
        POLICY_OVERWRITE,
        POLICY_SKIP,
        finalize_download,
    )

    obj = CameraObject(handle=1, storage_id=1, format=0x3801, size=4, filename="a.jpg")
    out = tmp_path / "out"
    out.mkdir()
    (out / "a.jpg").write_bytes(b"OLD!")

    # Skip: existing file untouched, .part removed, returns None.
    part = tmp_path / "p1.part"
    part.write_bytes(b"NEW!")
    assert (
        finalize_download(obj, str(out), str(part), "${original.name}", {}, policy=POLICY_SKIP)
        is None
    )
    assert (out / "a.jpg").read_bytes() == b"OLD!"
    assert not part.exists()

    # Overwrite: existing file replaced.
    part2 = tmp_path / "p2.part"
    part2.write_bytes(b"NEW!")
    result = finalize_download(
        obj, str(out), str(part2), "${original.name}", {}, policy=POLICY_OVERWRITE
    )
    assert result == str(out / "a.jpg")
    assert (out / "a.jpg").read_bytes() == b"NEW!"
