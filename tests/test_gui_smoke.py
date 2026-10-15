import os
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Keep QSettings out of the developer's real ~/.config during tests.
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp(prefix="canon-eos-test-config-")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from canon_eos_utility.mock import MockCameraServer  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _pump(app, predicate, timeout=15.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_gui_connect_gallery_and_download(qapp, tmp_path):
    from canon_eos_utility.ui.main_window import MainWindow

    server = MockCameraServer(port=0)
    server.start()
    window = MainWindow(enable_discovery=False)
    window.settings.download_dir = str(tmp_path)
    # Auto-delete so the post-download dialog is not shown (headless test).
    window.config.delete_after_download = True
    try:
        window.connection_bar.set_host(f"127.0.0.1:{server.port}")
        window._connect()

        assert _pump(qapp, lambda: window.gallery.list.count() > 0, timeout=20.0)
        assert window.gallery.list.count() >= 1

        handles = window.gallery.all_handles()[:1]
        window.worker.download_objects(handles, str(tmp_path))

        def _any_final_file():
            return any(
                path.is_file() and ".canon-eos-partial" not in path.parts
                for path in tmp_path.rglob("*")
            )

        assert _pump(qapp, _any_final_file, timeout=20)
        assert _any_final_file()
    finally:
        window.close()
        server.stop()


def test_gui_live_view_and_capture(qapp, tmp_path):
    from canon_eos_utility.ui.main_window import MainWindow

    server = MockCameraServer(port=0)
    server.start()
    window = MainWindow(enable_discovery=False)
    try:
        window.connection_bar.set_host(f"127.0.0.1:{server.port}")
        window._connect()
        assert _pump(qapp, lambda: window.gallery.list.count() > 0, timeout=20.0)

        before = window.gallery.list.count()
        window.worker.capture()
        assert _pump(
            qapp,
            lambda: window.gallery.list.count() == before + 1,
            timeout=20.0,
        )

        window.worker.set_live_view(True)
        assert _pump(
            qapp,
            lambda: window.live_view.view._pixmap is not None,
            timeout=20.0,
        )
    finally:
        window.close()
        server.stop()


#: A real EOS R5 hands out object handles above INT32_MAX (2_147_483_647).
BIG_HANDLE = 2442268945


def test_gallery_handles_above_int32(qapp):
    from canon_eos_utility.constants import ObjectFormat
    from canon_eos_utility.models import CameraObject
    from canon_eos_utility.ui.gallery_panel import GalleryPanel

    panel = GalleryPanel()
    panel.set_objects(
        [
            CameraObject(
                handle=BIG_HANDLE,
                storage_id=1,
                format=int(ObjectFormat.CR3),
                size=42,
                filename="IMG_0001.CR3",
            )
        ]
    )
    assert panel.all_handles() == [BIG_HANDLE]
    # Must not raise an overflow error for handles above INT32_MAX.
    panel.set_thumbnail(BIG_HANDLE, b"\xff\xd8\xff\xd9")


def test_worker_signals_carry_big_handles(qapp):
    from canon_eos_utility.ui.camera_worker import CameraWorker

    worker = CameraWorker("test", bytes(16))
    thumbs: list[tuple[int, bytes]] = []
    added: list[int] = []
    worker.thumbnailReady.connect(lambda handle, data: thumbs.append((handle, data)))
    worker.objectAdded.connect(added.append)

    worker.thumbnailReady.emit(BIG_HANDLE, b"jpeg")
    worker.objectAdded.emit(BIG_HANDLE)
    qapp.processEvents()

    assert thumbs == [(BIG_HANDLE, b"jpeg")]
    assert added == [BIG_HANDLE]


def test_download_resumes_after_connection_drop(qapp, tmp_path, monkeypatch):
    import canon_eos_utility.ui.camera_worker as cw
    from canon_eos_utility.ui.camera_worker import CameraWorker

    # Small chunks so a ~100 KB sample needs many GetPartialObject calls.
    monkeypatch.setattr(cw, "DOWNLOAD_CHUNK", 4096)

    server = MockCameraServer(port=0)
    server.start()
    worker = CameraWorker("test", bytes(16))
    worker.start()
    worker.set_download_config("${original.name}")

    objects: list = []
    errors: list[str] = []
    finished: list[int] = []
    worker.objectsLoaded.connect(lambda objs: objects.extend(objs))
    worker.errorOccurred.connect(lambda message: errors.append(message))
    worker.downloadFinished.connect(lambda total: finished.append(total))

    try:
        worker.connect_camera(f"127.0.0.1:{server.port}")
        assert _pump(qapp, lambda: len(objects) > 0, timeout=20)

        target = min((o for o in objects if o.is_image), key=lambda o: o.size)
        assert target.size > 8192 * 2

        # Drop the connection partway through the transfer.
        server.state.drop_partial_offset = 8192

        worker.download_objects([target.handle], str(tmp_path))
        assert _pump(qapp, lambda: len(finished) > 0, timeout=60)

        assert not errors, errors
        completed = [
            path
            for path in tmp_path.rglob("*")
            if path.is_file() and ".canon-eos-partial" not in path.parts
        ]
        assert len(completed) == 1
        assert completed[0].stat().st_size == target.size

        expected = server.state.find_image(target.handle)
        assert expected is not None
        assert completed[0].read_bytes() == expected.data
    finally:
        worker.stop()
        server.stop()


def test_auto_connect_on_mdns_discovery(qapp, tmp_path):
    from canon_eos_utility.discovery import DiscoveredCamera
    from canon_eos_utility.ui.main_window import MainWindow

    server = MockCameraServer(port=0)
    server.start()
    window = MainWindow(enable_discovery=False)
    try:
        window.connection_bar.set_auto_connect(True)
        window._on_camera_found(DiscoveredCamera(address="127.0.0.1", port=server.port))
        assert _pump(qapp, lambda: window.gallery.list.count() > 0, timeout=30)
    finally:
        window.close()
        server.stop()


def test_auto_connect_disabled_does_not_connect(qapp, tmp_path):
    from canon_eos_utility.discovery import DiscoveredCamera
    from canon_eos_utility.ui.main_window import MainWindow

    server = MockCameraServer(port=0)
    server.start()
    window = MainWindow(enable_discovery=False)
    try:
        window.connection_bar.set_auto_connect(False)
        window._on_camera_found(DiscoveredCamera(address="127.0.0.1", port=server.port))
        assert not _pump(qapp, lambda: window.gallery.list.count() > 0, timeout=3)
        assert window.worker.client is None
    finally:
        window.close()
        server.stop()


def test_downloads_resume_after_reconnect(qapp, tmp_path):
    from canon_eos_utility.ui.camera_worker import CameraWorker

    server = MockCameraServer(port=0)
    server.start()
    worker = CameraWorker("test", bytes(16))
    worker.set_download_config("${original.name}")

    finished: list[int] = []
    disconnected: list[bool] = []
    worker.downloadFinished.connect(lambda total: finished.append(total))
    worker.disconnected.connect(lambda: disconnected.append(True))

    host = f"127.0.0.1:{server.port}"
    try:
        # Drive the worker synchronously (thread not started) to avoid races.
        worker._do_connect(host)
        assert worker.client is not None

        target = min(
            (o for o in worker.client.list_objects() if o.is_image),
            key=lambda o: o.size,
        )
        worker._pending_downloads = [(target, str(tmp_path))]
        worker._download_total = 1

        # Simulate the camera vanishing completely.
        worker._handle_connection_loss()
        assert disconnected == [True]
        assert len(worker._pending_downloads) == 1  # queue preserved

        # Reconnecting should resume the pending download automatically.
        worker._do_connect(host)
        assert finished == [1]

        files = [
            path
            for path in tmp_path.rglob("*")
            if path.is_file() and ".canon-eos-partial" not in path.parts
        ]
        assert len(files) == 1
        expected = server.state.find_image(target.handle)
        assert expected is not None
        assert files[0].read_bytes() == expected.data
    finally:
        server.stop()


def test_worker_routes_videos_to_video_folder(qapp, tmp_path):
    from canon_eos_utility.config import AppConfig
    from canon_eos_utility.models import CameraObject
    from canon_eos_utility.ui.camera_worker import CameraWorker

    worker = CameraWorker("test", bytes(16))  # not started
    worker.set_config(
        AppConfig(
            download_directory=str(tmp_path / "photos"),
            filename_template="P/${original.name}",
            use_video_template=True,
            video_download_directory=str(tmp_path / "videos"),
            video_filename_template="V/${original.name}",
        )
    )
    photo = CameraObject(handle=1, storage_id=1, format=0x3801, size=1, filename="a.jpg")
    movie = CameraObject(handle=2, storage_id=1, format=0xB982, size=1, filename="m.mp4")
    fallback = str(tmp_path / "fallback")
    assert worker._output_for(photo, fallback) == (fallback, "P/${original.name}")
    assert worker._output_for(movie, fallback) == (
        str(tmp_path / "videos"),
        "V/${original.name}",
    )


def test_worker_overwrite_policy_from_config(qapp):
    from canon_eos_utility.config import AppConfig
    from canon_eos_utility.sync import POLICY_ASK, POLICY_OVERWRITE
    from canon_eos_utility.ui.camera_worker import CameraWorker

    worker = CameraWorker("test", bytes(16))
    assert worker._overwrite_policy == POLICY_ASK
    worker.set_config(AppConfig(always_overwrite=True))
    assert worker._overwrite_policy == POLICY_OVERWRITE
    worker.set_config(AppConfig(always_overwrite=False))
    assert worker._overwrite_policy == POLICY_ASK


def test_worker_conflict_prompt_and_apply_all(qapp):
    from canon_eos_utility.sync import POLICY_ASK, POLICY_SKIP
    from canon_eos_utility.ui.camera_worker import CameraWorker

    worker = CameraWorker("test", bytes(16))
    assert worker._overwrite_policy == POLICY_ASK
    seen: list[str] = []

    def answer(conflict):
        seen.append(conflict.target)
        conflict.overwrite = False
        conflict.apply_to_all = True
        conflict.event.set()

    worker.fileExists.connect(answer)
    assert worker._resolve_conflict("/tmp/x.jpg") == POLICY_SKIP
    assert worker._overwrite_policy == POLICY_SKIP  # apply-to-all stored
    # Subsequent conflicts use the stored policy without prompting again.
    assert worker._resolve_conflict("/tmp/y.jpg") == POLICY_SKIP
    assert seen == ["/tmp/x.jpg"]


def test_mainwindow_auto_deletes_when_configured(qapp):
    from canon_eos_utility.models import CameraObject
    from canon_eos_utility.ui.main_window import MainWindow

    window = MainWindow(enable_discovery=False)
    window.config.delete_after_download = True
    calls: list[list[int]] = []
    window.worker.delete_objects = lambda handles: calls.append(list(handles))
    obj = CameraObject(handle=5, storage_id=1, format=0x3801, size=1, filename="a.jpg")
    window._on_downloads_completed([obj])
    assert calls == [[5]]
    window.close()


def test_gallery_delete_button_emits_selected_handles(qapp):
    from PySide6.QtCore import Qt

    from canon_eos_utility.models import CameraObject
    from canon_eos_utility.ui.gallery_panel import GalleryPanel

    panel = GalleryPanel()
    panel.set_connected(True)
    panel.set_objects(
        [
            CameraObject(handle=1, storage_id=1, format=0x3801, size=1, filename="a.jpg"),
            CameraObject(handle=2, storage_id=1, format=0x3801, size=1, filename="b.jpg"),
        ]
    )
    got: list[list[int]] = []
    panel.deleteRequested.connect(lambda handles: got.append(list(handles)))

    assert not panel.delete_button.isEnabled()  # nothing selected
    panel.list.item(0).setSelected(True)
    assert panel.delete_button.isEnabled()
    panel._delete_selected()
    assert got == [[1]]

    panel.list.item(1).setCheckState(Qt.Checked)
    panel._delete_selected()
    assert set(got[-1]) == {1, 2}


def test_confirm_delete_uses_delete_objects(qapp, monkeypatch):
    from canon_eos_utility.ui import main_window as mw

    class _Dialog:
        @staticmethod
        def ask(*_args, **_kwargs):
            return (True, False)

    monkeypatch.setattr(mw, "ConfirmDialog", _Dialog)
    window = mw.MainWindow(enable_discovery=False)
    calls: list[list[int]] = []
    window.worker.delete_objects = lambda handles: calls.append(list(handles))
    window._confirm_delete([10, 11, 12])
    assert calls == [[10, 11, 12]]
    window.close()


def test_confirm_dialog_force_yes_disables_no(qapp):
    from canon_eos_utility.ui.dialogs import ConfirmDialog

    dialog = ConfirmDialog(
        None, "Title", "Message", checkbox_text="always", force_yes_when_checked=True
    )
    assert dialog.no_button.isEnabled()
    dialog.checkbox.setChecked(True)
    assert not dialog.no_button.isEnabled()
    dialog.checkbox.setChecked(False)
    assert dialog.no_button.isEnabled()


def test_gallery_iconless_item_has_full_hit_area(qapp):
    from canon_eos_utility.models import CameraObject
    from canon_eos_utility.ui.gallery_panel import GalleryPanel

    panel = GalleryPanel()
    panel.resize(600, 400)
    panel.set_connected(True)
    panel.set_objects(
        [CameraObject(handle=1, storage_id=1, format=0xB982, size=1, filename="movie.mp4")]
    )
    panel.show()
    qapp.processEvents()

    item = panel.list.item(0)
    rect = panel.list.visualItemRect(item)
    # The clickable rect must fill the cell even without a thumbnail.
    assert rect.width() >= 150
    assert rect.height() >= 150
    assert panel.list.itemAt(rect.center()) is item


def test_capture_waits_for_the_new_file(qapp):
    import time

    from canon_eos_utility.ui.camera_worker import CameraWorker

    server = MockCameraServer(port=0)
    server.start()
    # Simulate the camera taking a moment to write the file to the card.
    server.state.capture_delay_seconds = 1.2
    worker = CameraWorker("test", bytes(16))
    try:
        worker._do_connect(f"127.0.0.1:{server.port}")
        loaded: list = []
        worker.objectsLoaded.connect(lambda objs: (loaded.clear(), loaded.extend(objs)))

        start = time.monotonic()
        worker._do_capture()
        elapsed = time.monotonic() - start

        assert elapsed >= 1.0  # it waited for the file instead of refreshing immediately
        assert len(loaded) == 5  # 4 sample images + the new capture
    finally:
        server.stop()
