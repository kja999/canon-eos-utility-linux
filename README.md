# Canon EOS Utility for Linux

**Use your Canon EOS camera over Wi‑Fi from your Linux desktop.** Browse the
photos and movies on the camera's memory card, download them, watch a live view
of what the camera sees, and control the camera remotely — from a proper
desktop application.

## Why this exists

Canon only ships their **EOS Utility** software for Windows and macOS, and the
usual Linux camera tool, **libgphoto2**, does not yet support Canon's Wi‑Fi
"remote control" mode. This project fills that gap: it talks directly to the
camera over Wi‑Fi — the same way EOS Utility does — so Linux users can shoot
tethered-style and pull photos off the camera wirelessly.

> This is an independent, community project. It is not affiliated with or
> endorsed by Canon.

## What you can do

- **See what's on the camera** — a gallery of thumbnails with filenames, sizes
  and capture dates, right from the camera's card.
- **Download your photos and movies** — a selection, or everything at once.
  Large transfers survive hiccups: if the connection drops, they carry on from
  where they left off instead of starting over.
- **Watch Live View** — a live preview from the camera, with **touch‑to‑focus**:
  click anywhere in the image to move the focus point.
- **Take pictures remotely** — fire the shutter (with autofocus) without
  touching the camera, and the new photo appears in the gallery automatically.
- **Adjust the camera** — ISO, shutter speed, aperture and white balance, kept
  in sync with the camera.
- **Tidy up as you go** — choose how files are named and where they go, give
  videos their own folder, and optionally delete files from the camera once
  they've been safely downloaded.
- **Connect automatically** — listen for the camera's announcements on the
  network and connect automatically when it's there.

## Supported cameras

Any Canon EOS body with the **"Remote control (EOS Utility)"** Wi‑Fi mode works,
including the EOS R series (R, RP, R5, R6, R7, R8, R10, R50, R5 C…) and older
Wi‑Fi DSLRs (70D, 80D, 6D Mark II, 7D Mark II, 5D Mark IV, …).

---

## Installing

### Packages (recommended)

Download the latest packages from the
[releases page](https://github.com/night199uk/canon-eos-utility-linux/releases)
and install the one for your system:

```bash
# Flatpak (any distro)
flatpak install --user ./canon-eos-utility.flatpak

# Fedora / RHEL / openSUSE — GUI app
sudo rpm -i canon-eos-utility-*.x86_64.rpm
# …and/or the headless tools
sudo rpm -i canon-eos-utility-cli-*.x86_64.rpm

# Debian / Ubuntu — GUI app
sudo apt install ./canon-eos-utility_*_amd64.deb
# …and/or the headless tools
sudo apt install ./canon-eos-utility-cli_*_amd64.deb
```

Installing a package also adds the menu entry and icon, so the app launches from
your desktop's application menu like any other program.

### From source

If you prefer to run it from a checkout (you'll need Python 3.10+):

```bash
git clone https://github.com/night199uk/canon-eos-utility-linux.git
cd canon-eos-utility-linux
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
canon-eos-utility
```

## Connecting to your camera

1. On the camera, turn on Wi‑Fi and open
   **Wi‑Fi function → Remote control (EOS Utility)**.
2. Put the camera on your Wi‑Fi network (**Infrastructure mode**), or let it
   create its own network (**Camera access point mode**) and join that from your
   computer.
3. The camera shows a **pairing screen**. Start the app — it will find the camera
   automatically, or you can click **Scan network**, or type the camera's address
   (shown on its screen) into the **Camera** box.
4. The camera asks you to confirm the connection. Accept it and choose to
   **save the configuration** — you only have to do this once.

If the camera ever stops recognising the computer, use
**Camera → Reset pairing (new client identity)** and pair again.

## Using the app

| Where | What it does |
| --- | --- |
| **Camera bar** (top) | Find and connect to your camera. **Auto-connect** connects on its own when the camera appears. |
| **Gallery** (left) | Your camera's photos and movies. Tick the ones you want (or **Select all**) and press **Download selected**, or **Download all**. Double‑click to download one, or right‑click for more options. |
| **Delete** (below the gallery) | Removes the ticked/selected files from the camera's card, after asking you to confirm. |
| **Live View** (tools panel) | **Start live view** to see through the camera. Click the image to focus. |
| **Capture / Autofocus** | **Capture** takes a photo (with autofocus); **Autofocus** just focuses. |
| **Camera controls** (tools panel) | Set ISO, shutter speed, aperture and white balance. |

The **Live View and camera controls** panel is tucked behind the **Tools** button
on the right edge (or press `Ctrl+T`), since it's used less often.

By default, downloads go to `~/Pictures/Canon`. Change this in
**File → Settings…**.

## Naming and organising your files

Downloads are organised using a simple template. The default is:

```
Devices/${camera.model}/Recents/${capture.year}/${capture.month}/${capture.date}/${original.filename}.${original.extension}
```

…which sorts photos like this:

```
Devices/Canon EOS R5/Recents/2026/09/2026-09-12/246A8454.CR3
```

You can edit the template in **File → Settings…**, which shows a live preview as
you type. The available pieces include:

| Piece | Meaning |
| --- | --- |
| `${camera.model}` | Camera model (e.g. `Canon EOS R5`) |
| `${camera.serial}` | Camera serial number |
| `${original.name}` | Original filename **with** extension |
| `${original.filename}` / `${original.extension}` | Filename without extension / just the extension |
| `${capture.date}` | Capture date (`2026-09-12`) |
| `${capture.year}` / `${capture.month}` / `${capture.day}` | Date parts |
| `${capture.time}` | Capture time (`15:06:05`) |
| `${exif.iso}`, `${exif.f_number}`, `${exif.focal_length}`, `${exif.lens_model}` | Details read from the photo |
| `${image.width}` / `${image.height}` | Image size in pixels |

Dates are zero‑padded by default (`09`, `03`). Add `:d` for the unpadded number
(`${capture.month:d}` → `9`) or `:02d` to force padding.

**Videos in their own folder.** Tick
**Settings → “Use different directory & template for video files”** to give
movies a separate folder and naming rule.

**Files that already exist.** When a file is about to overwrite one you already
have, the app asks first (with an **Apply to all** option), or you can turn on
**Settings → “Always overwrite existing files”** to skip the question.

**Deleting from the camera.** After a download finishes and every file is
checked, the app offers to delete the copies from the camera. You can also make
that automatic with **Settings → “Always delete files after download”**.

## Automatic syncing (no GUI)

For grabbing photos without opening the app — for example on a small always‑on
machine — there's a headless companion, `canon-eos-daemon`. It watches for your
camera on the network and copies everything into your chosen folder as soon as
it appears, skipping files it has already imported.

```bash
canon-eos-daemon                                   # watch and sync automatically
canon-eos-daemon --host 192.168.0.100:15740 --once # one-off sync
```

It can run at login with the included systemd unit — see
`packaging/canon-eos-daemon.service`.

## Settings

Everything is configurable from **File → Settings…**, including the download
folder, naming templates, video handling, auto-connect, the theme accent colour,
and the overwrite/delete behaviour. The same settings live in a plain text file
if you'd rather edit them directly:

```
~/.config/canon-eos-utility-linux/config.toml
```

The accent colour follows your desktop theme by default; set it to a colour like
`#9141ac` to force one.

## Troubleshooting

- **The camera doesn't appear.** Make sure it's on the
  **Remote control (EOS Utility)** screen and on the same network as your
  computer. If discovery fails, type the camera's IP address into the **Camera**
  box. Some networks block the discovery broadcasts — the camera's own access
  point mode avoids that.
- **Connecting fails just after a previous session.** Canon cameras take a few
  seconds to accept a new connection; the app retries automatically. If it still
  won't connect, put the camera back on the pairing screen.
- **Live View is a little choppy.** The preview is refreshed a few times a
  second, which is normal for this kind of connection.

## Known limitations

- Live View is a few frames per second, so the preview is not smooth — the same
  is true of Canon's own software.
- Movie *recording* over Wi‑Fi isn't supported by most EOS bodies.
- Some very new camera models may report settings values this app doesn't yet
  have friendly names for; they'll still be shown, just as raw numbers.

---

## For developers

### Running the tests

```bash
pytest                              # all tests
QT_QPA_PLATFORM=offscreen pytest    # headless (no display)
ruff check src tests && ruff format src tests
```

### How it's put together

The camera communication lives in `src/canon_eos_utility/protocol/` and is plain
Python with no GUI dependency, so it can be reused or scripted on its own:

```python
from canon_eos_utility.protocol import CameraClient

with CameraClient(host="192.168.1.2") as camera:
    for obj in camera.list_objects():
        print(obj.filename, obj.size)
```

The rest is split between a shared, GUI‑free core (`sync.py`, `metadata.py`,
`naming.py`, `config.py`) used by both the app and the daemon, and the desktop
interface under `src/canon_eos_utility/ui/`.

### File‑naming reference

Every supported `${…}` path, in full:

| Path | Meaning |
| --- | --- |
| `${camera.model}` | Camera model |
| `${camera.manufacturer}` | Camera manufacturer |
| `${camera.serial}` | Camera serial number |
| `${camera.firmware}` | Camera firmware version |
| `${camera.name}` | Camera network name (e.g. `EOSR5_859408`) |
| `${original.name}` | Original filename **with** extension |
| `${original.filename}` | Original filename **without** extension |
| `${original.extension}` | Original extension (e.g. `CR3`) |
| `${capture.datetime}` | Capture date and time (supports `:%format`) |
| `${capture.date}` | Capture date `YYYY-MM-DD` |
| `${capture.year}` / `${capture.month}` / `${capture.day}` | Date parts |
| `${capture.week}` | ISO week number |
| `${capture.weekday}` / `${capture.weekday_name}` | Weekday number / name |
| `${capture.time}` / `${capture.hour}` / `${capture.minute}` / `${capture.second}` | Time parts |
| `${capture.epoch}` | Capture time as a Unix timestamp |
| `${image.width}` / `${image.height}` / `${image.size}` / `${image.format}` | Image details |
| `${exif.<tag>}` | Any EXIF value (see below) |

Convenient EXIF shortcuts: `${exif.make}`, `${exif.model}`,
`${exif.lens_model}`, `${exif.iso}`, `${exif.f_number}`,
`${exif.exposure_time}`, `${exif.focal_length}`, `${exif.datetime_original}`.
Any other `${exif.<tag>}` reads a raw EXIF tag; the full set of names is listed
in the source under `metadata.py`.

### Protocol notes

The implementation follows the CIPA PTP/IP specification draft (DC‑X005) and
Canon's vendor extensions. A few things worth knowing if you work on it:

- The camera advertises a `_ptp._tcp.local` service for discovery; the command
  and event channels both use TCP **15740**.
- Canon reports setting changes by *polling* `GetEventData` (~5×/s) rather than
  pushing them on the event channel.
- Downloads are chunked so they can resume.
- Setting a property carries a leading length field; omitting it makes the
  camera reply `DEVICE_BUSY`.
- Live View is enabled by switching the viewfinder on, routing the output to the
  host and keeping the camera awake; the first frame takes a moment to arrive.

References:

- Julian Schroden, *Exploring the PTP/IP Protocol* —
  <https://julianschroden.com/series/Exploring-the-PTP-IP-Protocol/1/>
- Mathias Mattern, *ptpip* — <https://github.com/mmattes/ptpip>
- CIPA PTP/IP specification draft —
  <https://www.cipa.jp/std/documents/e/DC-X005.pdf>

### Packaging

Release packages are built automatically on tags by the GitHub workflows. To
build locally:

```bash
# .deb and .rpm for the GUI and CLI (needs nfpm: https://nfpm.goreleaser.com/)
packaging/build_packages.sh
ls dist/packages/

# Flatpak bundle
flatpak-builder --user --install --force-clean build-dir \
  packaging/flatpak/org.problem_child.CanonEOSUtility.yml
```

The Flatpak uses the KDE runtime plus Flathub's Qt base app, and vendors
its Python dependencies so it builds offline. The manifest is Flathub‑ready
(pending a submission).

## License

GPL‑3.0‑or‑later.
