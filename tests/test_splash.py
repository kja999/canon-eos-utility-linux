import os
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Keep QSettings out of the developer's real ~/.config during tests.
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp(prefix="canon-eos-test-config-")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _pump(app, predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_splash_shows_name_author_and_logo(qapp):
    from canon_eos_utility import APP_AUTHOR, APP_NAME
    from canon_eos_utility.ui.splash import SplashScreen
    from canon_eos_utility.ui.theme import apply_widget_theme

    splash = SplashScreen()
    apply_widget_theme(splash)

    assert splash.objectName() == "splashRoot"
    assert splash._card.objectName() == "splashCard"
    labels = {label.objectName(): label.text() for label in splash.findChildren(QLabel)}
    assert labels["splashTitle"] == APP_NAME
    assert labels["splashAuthor"] == APP_AUTHOR
    # The logo pixmap is rendered, not empty.
    logo = next(w for w in splash.findChildren(QLabel) if not w.objectName())
    assert logo.pixmap() is not None and not logo.pixmap().isNull()


def test_splash_auto_closes_after_its_duration(qapp):
    from canon_eos_utility.ui.splash import SplashScreen
    from canon_eos_utility.ui.theme import apply_widget_theme

    splash = SplashScreen(duration_ms=200)
    apply_widget_theme(splash)
    splash.start()

    assert splash.isVisible()
    assert _pump(qapp, lambda: not splash.isVisible(), timeout=3.0)
