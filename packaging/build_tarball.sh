#!/usr/bin/env bash
#
# Build a self-contained, relocatable tarball of the GUI app for FlatPark.
#
# FlatPark only repackages a vendor's prebuilt download (extra-data); this
# produces that download.  The bundle carries its own Python + PySide6/Qt, so it
# runs inside the freedesktop Flatpak runtime with nothing else installed.
#
# Requires: python3 and pip (PySide6 is pulled in as a build dependency).
# Output:   dist/bundle/canon-eos-utility-<version>-<arch>.tar.xz
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

VERSION="${1:-$(python3 - <<'PY'
import tomllib
print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])
PY
)}"
ARCH="$(uname -m)"
OUT="$REPO_ROOT/dist/bundle"
BUNDLE="$OUT/canon-eos-utility"

echo ">> Installing build dependencies"
python3 -m pip install --quiet --upgrade pip pyinstaller
python3 -m pip install --quiet .

echo ">> Building bundle with PyInstaller"
rm -rf "$BUNDLE"
python3 -m PyInstaller --clean --noconfirm \
  --distpath "$OUT" \
  --workpath "$REPO_ROOT/build/pyinstaller" \
  packaging/canon-eos-utility.spec

TARBALL="$OUT/canon-eos-utility-${VERSION}-${ARCH}.tar.xz"
echo ">> Packing $TARBALL"
rm -f "$TARBALL"
tar -cJf "$TARBALL" -C "$OUT" canon-eos-utility

echo ">> Bundle written to $TARBALL"
ls -lh "$TARBALL"
