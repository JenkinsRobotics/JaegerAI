#!/usr/bin/env bash
#
# build-shell.sh — assemble the JaegerShell dev app (debug only).
#
#   Output:    ~/.cache/jaeger/macos-shell/JaegerShell.app (JAEGER_MAC_BUILD overrides)
#   Bundle ID: com.jenkinsrobotics.JaegerAI.uirebuild                   (asserted)
#
# It never builds release, never installs, never touches JaegerAI.app (either
# location), launchd or the venv. Takes no arguments; never installs or launches.
set -euo pipefail
[[ $# -eq 0 ]] || { echo "build-shell.sh takes no arguments (debug only)" >&2; exit 2; }

PKG="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO="$(git -C "$PKG" rev-parse --show-toplevel)"
ROOT="$(bash "$PKG/Scripts/build-root.sh")"
SCRATCH="$ROOT/scratch"
APP="$ROOT/JaegerShell.app"
WANT_ID="com.jenkinsrobotics.JaegerAI.uirebuild"
mkdir -p "$ROOT"

echo "[build-shell] swift build -c debug --scratch-path $SCRATCH"
swift build -c debug --package-path "$PKG" --scratch-path "$SCRATCH"
BIN="$(swift build -c debug --package-path "$PKG" --scratch-path "$SCRATCH" --show-bin-path)"
[[ -x "$BIN/JaegerShell" ]] || { echo "[build-shell] missing $BIN/JaegerShell" >&2; exit 1; }

STAGE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/jaeger-shell.XXXXXX")"
trap 'rm -rf "$STAGE_DIR"' EXIT
STAGE="$STAGE_DIR/JaegerShell.app"
mkdir -p "$STAGE/Contents/MacOS" "$STAGE/Contents/Resources"
cp "$PKG/Resources/Info.plist" "$STAGE/Contents/Info.plist"
ID="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$STAGE/Contents/Info.plist")"
[[ "$ID" == "$WANT_ID" ]] || { echo "[build-shell] wrong bundle id: $ID" >&2; exit 1; }
VER="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$REPO/jaeger_ai/__init__.py")"
SHA="$(git -C "$REPO" rev-parse --short HEAD)"
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString ${VER:-0.0.0}" \
    -c "Set :CFBundleVersion ${VER:-0.0.0}+$SHA" "$STAGE/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Add :JaegerLauncher string $REPO/jaeger" "$STAGE/Contents/Info.plist"
cp "$BIN/JaegerShell" "$STAGE/Contents/MacOS/JaegerShell"

# Loose resources (status-bar icons etc.) go straight into Contents/Resources.
if compgen -G "$PKG/Resources/*.png" >/dev/null; then cp "$PKG"/Resources/*.png "$STAGE/Contents/Resources/"; fi

# AppIcon.icns from the Jaeger app icon PNGs (same mapping as interfaces/swift/Scripts/build-app.sh).
A="$REPO/jaeger_ai/assets"
ICONSET="$STAGE_DIR/AppIcon.iconset"; mkdir -p "$ICONSET"
cp "$A/jaeger_app_icon_16.png"  "$ICONSET/icon_16x16.png"
cp "$A/jaeger_app_icon_32.png"  "$ICONSET/icon_16x16@2x.png"
cp "$A/jaeger_app_icon_32.png"  "$ICONSET/icon_32x32.png"
cp "$A/jaeger_app_icon_64.png"  "$ICONSET/icon_32x32@2x.png"
cp "$A/jaeger_app_icon_128.png" "$ICONSET/icon_128x128.png"
cp "$A/jaeger_app_icon_256.png" "$ICONSET/icon_128x128@2x.png"
cp "$A/jaeger_app_icon_256.png" "$ICONSET/icon_256x256.png"
cp "$A/jaeger_app_icon_512.png" "$ICONSET/icon_256x256@2x.png"
cp "$A/jaeger_app_icon_512.png" "$ICONSET/icon_512x512.png"
cp "$A/jaeger_app_icon.png"     "$ICONSET/icon_512x512@2x.png"
iconutil -c icns -o "$STAGE/Contents/Resources/AppIcon.icns" "$ICONSET"

git -C "$REPO" rev-parse HEAD > "$STAGE/Contents/Resources/build-commit"
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$REPO" python3 -B - "$REPO" <<'PY' > "$STAGE/Contents/Resources/build-source-hash"
from pathlib import Path
from jaeger_ai.cli._common import mac_source_fingerprint
import sys
print(mac_source_fingerprint(Path(sys.argv[1])))
PY
codesign --force --sign - "$STAGE"
codesign --verify --deep --strict "$STAGE"

if [[ -e "$APP" ]]; then
    /usr/bin/pgrep -f "^$APP/Contents/MacOS/JaegerShell" >/dev/null && { echo "Refusing to replace a running shell" >&2; exit 1; }
    PREVIOUS="$ROOT/previous/$(date +%Y%m%d-%H%M%S)-$$"
    mkdir -p "$PREVIOUS"
    mv "$APP" "$PREVIOUS/JaegerShell.app"
fi
mv "$STAGE" "$APP"
echo "$APP"
