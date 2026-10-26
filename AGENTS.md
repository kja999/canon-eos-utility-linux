# AGENTS.md

Guidance for automated agents working in this repository.

## Project

`canon-eos-utility-linux` — a PySide6 (Qt for Python) desktop client that talks
to Canon EOS cameras over WiFi using the PTP/IP protocol. It browses and
downloads images and provides remote control (Live View, capture, ISO/shutter/
aperture/white-balance) plus a built-in **mock camera** for development.

## Commands

```bash
# Run the app (needs PySide6)
python -m canon_eos_utility

# Run the mock camera
python -m canon_eos_utility.mock --host 127.0.0.1 --port 15740

# Run the headless auto-sync daemon
python -m canon_eos_utility.daemon            # watch mDNS, sync everything
python -m canon_eos_utility.daemon --host 127.0.0.1:15740 --once

# Tests (GUI tests need the offscreen platform when headless)
pytest
QT_QPA_PLATFORM=offscreen pytest

# Lint / format
ruff check src tests
ruff format src tests

# Editable install
pip install -e ".[dev]"

# Packaging (needs nfpm on PATH): builds GUI + CLI .deb and .rpm
packaging/build_packages.sh

# Flatpak — how the app is installed on this PC. Build it INSIDE the toolbox;
# the host has no flatpak-builder. `-u keitha` is required (as root, bwrap dies
# with "Can't find source path /proc/self/fd/12"), and HOME must point at the
# host home so the install lands on the host's user instance.
podman exec -u keitha -e HOME=$HOME -w "$PWD" fedora-toolbox-44 bash -c \
  'flatpak-builder --user --install --force-clean --state-dir=/tmp/kstate /tmp/kbuild \
     packaging/flatpak/org.problem_child.CanonEOSUtility.yml'
flatpak run org.problem_child.CanonEOSUtility
```

**Full Flatpak procedure, failure modes and verification recipe:** see the note
*"Canon EOS Utility — local Flatpak install process (build in toolbox)"* —
http://192.168.1.200:9991/#root/xOpvLWyDcGvH/4xnsIMiydtTQ .

## Branches

- `main` mirrors `night199uk/canon-eos-utility-linux` (remote `upstream`) and
  carries **no local work**. Each change lives on its own topic branch off
  `main` (`fix/…`, `feat/…`, `docs/…`) with one commit and its tests, and is
  pushed to the fork at `origin` (`kja999/canon-eos-utility-linux`) for
  reference — upstream is not contacted unless asked.
- `local/integration` merges the topic branches and is **the branch to install
  and test from**. Building the Flatpak from `main` silently ships upstream's
  code — e.g. it reverts the gallery checkbox fix.

## Architecture rules

- `src/canon_eos_utility/protocol/` is **pure Python and must not import Qt**.
  Keep the PTP/IP stack reusable and unit-testable.
- All blocking camera I/O runs on the worker thread in
  `src/canon_eos_utility/ui/camera_worker.py`.  The GUI thread only posts
  commands and reacts to signals — never call `CameraClient` from the GUI thread.
- `sync.py` (download/resume + naming) and `metadata.py`/`naming.py`/`config.py`
  are Qt-free and shared by both the GUI and the headless `daemon.py`.  Keep them
  importable without PySide6.
- UI styling lives in `ui/theme.py`; the bundled Poppins fonts under
  `ui/fonts/` are registered at startup and shipped via `package-data`.  Prefer
  the theme over per-widget inline stylesheets so styling stays consistent.
- Use the themed dialogs in `ui/dialogs.py` (`ConfirmDialog`, `MessageDialog`)
  instead of `QMessageBox`, which keeps its platform icon/spacing.
- Prefer the documented protocol constants in `constants.py` over magic numbers.
- After changing wire formats, add/extend tests in `tests/` and make sure the
  mock server (`mock/server.py`) and client (`protocol/client.py`) stay in sync.

## Testing notes

- `tests/test_client_mock.py` exercises the real client against the mock server
  on an ephemeral port — this is the main integration safety net.
- `tests/test_gui_smoke.py` builds the whole `MainWindow` offscreen and drives a
  mock connection, download, capture, Live View, mDNS auto-connect and a
  mid-transfer resume.  Tests must pass `MainWindow(enable_discovery=False)` so
  they do not start a real mDNS browser.
- `tests/test_discovery.py` covers the DNS-SD listener mapping (skipped if
  `zeroconf` is missing).
- `tests/test_naming.py`, `tests/test_metadata.py` and `tests/test_config.py`
  cover the file-naming template engine, EXIF/CR3/MP4 metadata extraction and
  the TOML config.
- `tests/test_sync.py` and `tests/test_daemon.py` cover the Qt-free download
  primitives and the headless daemon against the mock (including skip-already-
  downloaded state).
- Pillow, zeroconf and exif are required for the mock camera, discovery and
  metadata respectively (and therefore those tests).
- The mock can advertise over mDNS for manual end-to-end testing:
  `python -m canon_eos_utility.mock --advertise`.
