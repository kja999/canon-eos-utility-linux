# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec: a self-contained, relocatable onedir bundle of the GUI app.

This is the artifact FlatPark repackages as extra-data.  The bundle carries its
own Python interpreter, PySide6/Qt and the third-party dependencies, so it runs
inside the freedesktop Flatpak runtime with nothing else installed.

Build it with ``packaging/build_tarball.sh`` (which also tars the result).
"""

from pathlib import Path

SPEC_DIR = Path(SPECPATH).resolve()  # .../packaging
REPO = SPEC_DIR.parent
SRC = REPO / "src"

# Ship the bundled Poppins fonts (and their licence) next to the package.
datas = [
    (str(SRC / "canon_eos_utility" / "ui" / "fonts"), "canon_eos_utility/ui/fonts"),
]

a = Analysis(
    [str(SPEC_DIR / "pyinstaller_entry.py")],
    pathex=[str(SRC)],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # The mock camera (Pillow) and anything else the GUI never touches.
    excludes=["canon_eos_utility.mock", "PIL", "tkinter"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="canon-eos-utility",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="canon-eos-utility",
)
