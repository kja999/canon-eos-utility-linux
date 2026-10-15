#!/usr/bin/env bash
#
# Build .deb and .rpm packages for the GUI and for the CLI tools.
#
# Requires: python3, pip, and nfpm on PATH.
# Output:   dist/packages/*.deb and *.rpm
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

APP_ID="org.problem_child.CanonEOSUtility"
PKG="canon-eos-utility"
CLI_PKG="canon-eos-utility-cli"
MAINTAINER="canon-eos-utility-linux contributors"
HOMEPAGE="https://github.com/canon-eos-utility-linux/canon-eos-utility-linux"
INSTALL_DIR="/usr/lib/canon-eos-utility"

VERSION="${1:-$(python3 - <<'PY'
import tomllib
print(tomllib.load(open("pyproject.toml", "rb"))["project"]["version"])
PY
)}"

OUT="$REPO_ROOT/dist/packages"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$OUT"

echo ">> Building wheel for $PKG $VERSION"
python3 -m pip install --quiet --upgrade build >/dev/null
rm -f "$REPO_ROOT"/dist/*.whl 2>/dev/null || true
python3 -m build --wheel --outdir "$REPO_ROOT/dist" >/dev/null
WHEEL="$(ls "$REPO_ROOT"/dist/*.whl | head -1)"

echo ">> Vendoring pure-Python dependencies"
VENDOR="$WORK/vendor"
python3 -m pip install --quiet --target "$VENDOR" zeroconf exif
python3 -m pip install --quiet --no-deps --target "$VENDOR" "$WHEEL"
find "$VENDOR" -maxdepth 1 -name "*.dist-info" -exec rm -rf {} + 2>/dev/null || true
# Drop build-machine byte-code and console scripts.
find "$VENDOR" -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
find "$VENDOR" -name "*.pyc" -delete 2>/dev/null || true
rm -rf "$VENDOR/bin"

write_wrapper() {
  local path="$1" module="$2" func="$3"
  cat > "$path" <<EOF
#!/usr/bin/python3
import sys
sys.path.insert(0, "$INSTALL_DIR")
from $module import $func
raise SystemExit($func())
EOF
  chmod 0755 "$path"
}

stage_common() {
  local dest="$1"
  mkdir -p "$dest$INSTALL_DIR" "$dest/usr/bin"
  cp -a "$VENDOR/." "$dest$INSTALL_DIR/"
}

# --- GUI package ----------------------------------------------------------
GUI="$WORK/gui"
stage_common "$GUI"
write_wrapper "$GUI/usr/bin/canon-eos-utility" "canon_eos_utility.app" "run"
mkdir -p "$GUI/usr/share/applications" "$GUI/usr/share/metainfo" \
  "$GUI/usr/share/icons/hicolor/scalable/apps"
cp "packaging/$APP_ID.desktop" "$GUI/usr/share/applications/$APP_ID.desktop"
cp "packaging/$APP_ID.metainfo.xml" "$GUI/usr/share/metainfo/$APP_ID.metainfo.xml"
cp "packaging/icons/$APP_ID.svg" "$GUI/usr/share/icons/hicolor/scalable/apps/$APP_ID.svg"

# --- CLI package ----------------------------------------------------------
CLI="$WORK/cli"
stage_common "$CLI"
write_wrapper "$CLI/usr/bin/canon-eos-daemon" "canon_eos_utility.daemon" "main"
write_wrapper "$CLI/usr/bin/canon-eos-mock" "canon_eos_utility.mock.__main__" "main"

gen_nfpm() {
  local dest="$1" name="$2" desc="$3" depends="$4" file="$5"
  cat > "$file" <<EOF
name: "$name"
arch: amd64
platform: linux
version: "$VERSION"
section: graphics
priority: optional
maintainer: "$MAINTAINER"
vendor: canon-eos-utility-linux
homepage: "$HOMEPAGE"
license: GPL-3.0-or-later
description: |
  $desc
depends:
$depends
contents:
  - src: "$dest/usr"
    dst: /usr
EOF
}

echo ">> Generating nfpm configs"
gen_nfpm "$GUI" "$PKG" \
  "Qt GUI client for Canon EOS cameras over WiFi (PTP/IP)." \
  $'  - python3\n  - python3-pyside6' \
  "$WORK/gui.yaml"
gen_nfpm "$CLI" "$CLI_PKG" \
  "Headless Canon EOS auto-sync daemon and mock camera (CLI tools)." \
  $'  - python3\n  - python3-pillow' \
  "$WORK/cli.yaml"

build_one() {
  local cfg="$1" pkgname="$2"
  for packager in deb rpm; do
    echo ">> Building $packager for $pkgname"
    nfpm package --config "$cfg" --packager "$packager" --target "$OUT/"
  done
}

build_one "$WORK/gui.yaml" "$PKG"
build_one "$WORK/cli.yaml" "$CLI_PKG"

echo ">> Packages written to $OUT:"
ls -1 "$OUT"
