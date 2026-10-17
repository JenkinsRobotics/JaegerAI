#!/usr/bin/env bash
#
# build-shell.sh — assemble the JaegerShell dev app (debug only).
#
#   Output:    <macos-shell>/.build/ui-rebuild/JaegerShell.app   (fixed, gitignored, no override)
#   Bundle ID: com.jenkinsrobotics.JaegerAI.uirebuild                   (asserted)
#
# It never builds release, never installs, never touches JaegerAI.app (either
# location), launchd, ~/.jaeger (refused as a build root) or the venv. Takes no arguments.
set -euo pipefail
[[ $# -eq 0 ]] || { echo "build-shell.sh takes no arguments (debug only)" >&2; exit 2; }

PKG="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO="$(git -C "$PKG" rev-parse --show-toplevel)"
ROOT="$PKG/.build/ui-rebuild"
# Guards: never under ~/.jaeger; only inside this package's gitignored .build folder.
case "$ROOT/" in "$HOME/.jaeger/"*) echo "build root under ~/.jaeger is refused" >&2; exit 1 ;; esac
case "$ROOT/" in "$PKG/.build/"*) ;; *) echo "build root must be inside $PKG/.build" >&2; exit 1 ;; esac
git -C "$PKG" check-ignore -q "$ROOT" || { echo "build root is not gitignored" >&2; exit 1; }
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
codesign --force --sign - "$STAGE"
codesign --verify --deep --strict "$STAGE"

rm -rf "$APP"          # the only path this script ever replaces
mv "$STAGE" "$APP"
echo "$APP"
