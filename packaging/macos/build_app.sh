#!/bin/bash
# Builds "Concall Player.app" and a drag-to-install DMG. Runs on macOS (CI).
#   packaging/macos/build_app.sh [output-dir]
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
OUT="${1:-$ROOT/dist}"
UV_VERSION="${UV_VERSION:-0.12.23}"
VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$ROOT/concall/__init__.py")"
APP="$OUT/Concall Player.app"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "Building Concall Player $VERSION"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/app"

cp "$HERE/launcher.sh" "$APP/Contents/MacOS/Concall Player"
chmod +x "$APP/Contents/MacOS/Concall Player"
sed "s/__VERSION__/$VERSION/g" "$HERE/Info.plist" > "$APP/Contents/Info.plist"
plutil -lint "$APP/Contents/Info.plist"

# The app's own code (updates later replace this from inside the app).
cp -R "$ROOT/concall" "$APP/Contents/Resources/app/"
cp "$ROOT"/requirements*.txt "$APP/Contents/Resources/app/"
find "$APP/Contents/Resources/app" -name "__pycache__" -type d -prune -exec rm -rf {} +

# uv: installs Python and packages on first launch.
python3 -m pip download "uv==$UV_VERSION" --only-binary=:all: --platform macosx_11_0_arm64 --no-deps -d "$TMP/uv" -q
unzip -q -j "$TMP"/uv/uv-*.whl "uv-$UV_VERSION.data/scripts/uv" -d "$APP/Contents/Resources/"
chmod +x "$APP/Contents/Resources/uv"

# Icon
python3 "$HERE/make_icon.py" "$TMP/AppIcon.iconset"
iconutil -c icns "$TMP/AppIcon.iconset" -o "$APP/Contents/Resources/AppIcon.icns"

# Ad-hoc signature (no Apple Developer account): macOS asks once to "Open Anyway".
codesign --force --deep --sign - "$APP"
codesign --verify --deep "$APP"

# Disk image with an Applications shortcut to drag onto.
mkdir -p "$TMP/dmg"
cp -R "$APP" "$TMP/dmg/"
ln -s /Applications "$TMP/dmg/Applications"
rm -f "$OUT/Concall-Player.dmg"
hdiutil create -volname "Concall Player" -srcfolder "$TMP/dmg" -ov -format UDZO "$OUT/Concall-Player.dmg" >/dev/null
echo "Built: $APP"
echo "Built: $OUT/Concall-Player.dmg ($(du -h "$OUT/Concall-Player.dmg" | cut -f1))"
