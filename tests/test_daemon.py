from canon_eos_utility.config import AppConfig
from canon_eos_utility.daemon import CameraDaemon
from canon_eos_utility.mock import MockCameraServer

GUID = "aa" * 16


def _config(tmp_path) -> AppConfig:
    return AppConfig(
        filename_template="${original.name}",
        download_directory=str(tmp_path),
        client_guid=GUID,
        client_name="daemon-test",
    )


def _completed_files(tmp_path):
    return [
        path
        for path in tmp_path.rglob("*")
        if path.is_file()
        and ".canon-eos-partial" not in path.parts
        and path.name != ".canon-eos-sync.json"
    ]


def test_daemon_syncs_once_and_skips_next_run(tmp_path):
    server = MockCameraServer(port=0)
    server.start()
    config = _config(tmp_path)

    logs: list[str] = []
    daemon = CameraDaemon(config, host=f"127.0.0.1:{server.port}", once=True, log=logs.append)
    try:
        assert daemon.run() == 0
        assert len(_completed_files(tmp_path)) == 4
        assert (tmp_path / ".canon-eos-sync.json").exists()

        # Second run sees everything already present and downloads nothing new.
        daemon2 = CameraDaemon(config, host=f"127.0.0.1:{server.port}", once=True, log=logs.append)
        assert daemon2.run() == 0
        assert len(_completed_files(tmp_path)) == 4
    finally:
        server.stop()


def test_daemon_uses_templated_subdirectories(tmp_path):
    server = MockCameraServer(port=0)
    server.start()
    config = _config(tmp_path)
    config.filename_template = "${camera.model}/${original.name}"
    daemon = CameraDaemon(config, host=f"127.0.0.1:{server.port}", once=True, log=lambda _m: None)
    try:
        assert daemon.run() == 0
        nested = list(tmp_path.glob("Canon EOS 70D (mock)/IMG_*.JPG"))
        assert len(nested) == 4
    finally:
        server.stop()


def test_daemon_no_overwrite_skips_existing(tmp_path):
    from canon_eos_utility.sync import POLICY_SKIP

    server = MockCameraServer(port=0)
    server.start()
    config = _config(tmp_path)
    existing = tmp_path / "IMG_0001.JPG"
    existing.write_bytes(b"EXISTING")
    try:
        daemon = CameraDaemon(
            config,
            host=f"127.0.0.1:{server.port}",
            once=True,
            log=lambda _m: None,
            overwrite_policy=POLICY_SKIP,
        )
        assert daemon.run() == 0
        assert existing.read_bytes() == b"EXISTING"  # untouched
        assert (tmp_path / "IMG_0002.JPG").exists()  # others still downloaded
    finally:
        server.stop()


def test_daemon_always_overwrite_replaces_existing(tmp_path):
    from canon_eos_utility.sync import POLICY_OVERWRITE

    server = MockCameraServer(port=0)
    server.start()
    config = _config(tmp_path)
    existing = tmp_path / "IMG_0001.JPG"
    existing.write_bytes(b"EXISTING")
    try:
        daemon = CameraDaemon(
            config,
            host=f"127.0.0.1:{server.port}",
            once=True,
            log=lambda _m: None,
            overwrite_policy=POLICY_OVERWRITE,
        )
        assert daemon.run() == 0
        assert existing.read_bytes().startswith(b"\xff\xd8\xff")
    finally:
        server.stop()


def test_daemon_ask_overwrite_non_interactive_skips(tmp_path):
    from canon_eos_utility.sync import POLICY_ASK, POLICY_SKIP

    config = _config(tmp_path)
    daemon = CameraDaemon(config, log=lambda _m: None)
    assert daemon._current_policy == POLICY_ASK
    assert daemon._ask_overwrite("/tmp/some/file.jpg") == POLICY_SKIP
