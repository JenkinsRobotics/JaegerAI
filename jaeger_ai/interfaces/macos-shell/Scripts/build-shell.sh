#!/usr/bin/env bash
#
# build-shell.sh — assemble the JaegerAI macOS desktop + menubar app bundle.
#
#   Output:    ~/.cache/jaeger/macos-shell/JaegerAI.app (JAEGER_MAC_BUILD overrides)
#   Scratch:   ~/.cache/jaeger/macos-shell-build        (JAEGER_MAC_SCRATCH overrides)
#   Bundle ID: com.jenkinsrobotics.JaegerAI             (asserted)
#
# Options:
#   --install [path]  Also install the signed bundle to /Applications/JaegerAI.app (or [path]).
#   JAEGER_MAC_CONFIGURATION=release|debug (default: release)
#   JAEGER_LAUNCHER=<path>                 (default: <repo>/jaeger)
set -euo pipefail

INSTALL_TARGET="${JAEGER_MAC_INSTALL:-}"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --install)
            if [[ $# -ge 2 && "$2" != --* ]]; then
                INSTALL_TARGET="$2"
                shift 2
            else
                INSTALL_TARGET="/Applications/JaegerAI.app"
                shift
            fi
            ;;
        *)
            echo "Unknown argument: $1" >&2
            exit 2
            ;;
    esac
done

CONFIGURATION="${JAEGER_MAC_CONFIGURATION:-release}"
case "$CONFIGURATION" in debug|release) ;; *) echo "Invalid Mac configuration: $CONFIGURATION" >&2; exit 2 ;; esac

PKG="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO="$(cd "$PKG/../../.." && pwd)"
ROOT="$(bash "$PKG/Scripts/build-root.sh")"
SCRATCH="${JAEGER_MAC_SCRATCH:-$HOME/.cache/jaeger/macos-shell-build}"
APP="$ROOT/JaegerAI.app"
WANT_ID="com.jenkinsrobotics.JaegerAI"
LAUNCHER="${JAEGER_LAUNCHER:-$REPO/jaeger}"
mkdir -p "$ROOT" "$SCRATCH"

echo "[build-shell] swift build -c $CONFIGURATION --scratch-path $SCRATCH"
swift build -c "$CONFIGURATION" --package-path "$PKG" --scratch-path "$SCRATCH"
BIN="$(swift build -c "$CONFIGURATION" --package-path "$PKG" --scratch-path "$SCRATCH" --show-bin-path)"
[[ -x "$BIN/JaegerShell" ]] || { echo "[build-shell] missing $BIN/JaegerShell" >&2; exit 1; }

STAGE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/jaeger-shell.XXXXXX")"
trap 'rm -rf "$STAGE_DIR"' EXIT
STAGE="$STAGE_DIR/JaegerAI.app"
mkdir -p "$STAGE/Contents/MacOS" "$STAGE/Contents/Resources"
cp "$PKG/Resources/Info.plist" "$STAGE/Contents/Info.plist"

ID="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$STAGE/Contents/Info.plist")"
[[ "$ID" == "$WANT_ID" ]] || { echo "[build-shell] wrong bundle id: $ID (expected $WANT_ID)" >&2; exit 1; }

VER="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$REPO/jaeger_ai/__init__.py")"
SHA="$(git -C "$REPO" rev-parse --short HEAD 2>/dev/null || printf archive)"
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString ${VER:-1.0.0}" \
    -c "Set :CFBundleVersion ${VER:-1.0.0}+$SHA" "$STAGE/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Delete :JaegerLauncher" "$STAGE/Contents/Info.plist" 2>/dev/null || true
/usr/libexec/PlistBuddy -c "Add :JaegerLauncher string $LAUNCHER" "$STAGE/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Delete :JaegerDevBuild" "$STAGE/Contents/Info.plist" 2>/dev/null || true
plutil -lint "$STAGE/Contents/Info.plist" >/dev/null

cp "$BIN/JaegerShell" "$STAGE/Contents/MacOS/JaegerShell"

# Loose resources (status-bar icons etc.) go straight into Contents/Resources.
if compgen -G "$PKG/Resources/*.png" >/dev/null; then
    cp "$PKG"/Resources/*.png "$STAGE/Contents/Resources/"
fi

# AppIcon.icns: build from jaeger_ai/assets PNGs when present, else use bundled Resources/AppIcon.icns.
ASSETS_DIR="$REPO/jaeger_ai/assets"
if [[ -f "$ASSETS_DIR/jaeger_app_icon_16.png" && -f "$ASSETS_DIR/jaeger_app_icon.png" ]]; then
    ICONSET="$STAGE_DIR/AppIcon.iconset"; mkdir -p "$ICONSET"
    cp "$ASSETS_DIR/jaeger_app_icon_16.png"  "$ICONSET/icon_16x16.png"
    cp "$ASSETS_DIR/jaeger_app_icon_32.png"  "$ICONSET/icon_16x16@2x.png"
    cp "$ASSETS_DIR/jaeger_app_icon_32.png"  "$ICONSET/icon_32x32.png"
    cp "$ASSETS_DIR/jaeger_app_icon_64.png"  "$ICONSET/icon_32x32@2x.png"
    cp "$ASSETS_DIR/jaeger_app_icon_128.png" "$ICONSET/icon_128x128.png"
    cp "$ASSETS_DIR/jaeger_app_icon_256.png" "$ICONSET/icon_128x128@2x.png"
    cp "$ASSETS_DIR/jaeger_app_icon_256.png" "$ICONSET/icon_256x256.png"
    cp "$ASSETS_DIR/jaeger_app_icon_512.png" "$ICONSET/icon_256x256@2x.png"
    cp "$ASSETS_DIR/jaeger_app_icon_512.png" "$ICONSET/icon_512x512.png"
    cp "$ASSETS_DIR/jaeger_app_icon.png"     "$ICONSET/icon_512x512@2x.png"
    iconutil -c icns -o "$STAGE/Contents/Resources/AppIcon.icns" "$ICONSET"
elif [[ -f "$PKG/Resources/AppIcon.icns" ]]; then
    cp "$PKG/Resources/AppIcon.icns" "$STAGE/Contents/Resources/AppIcon.icns"
else
    echo "[build-shell] missing AppIcon.icns and jaeger_ai/assets icon PNGs" >&2
    exit 1
fi

git -C "$REPO" rev-parse HEAD > "$STAGE/Contents/Resources/build-commit" 2>/dev/null || printf "archive\n" > "$STAGE/Contents/Resources/build-commit"
(
    cd "$PKG"
    find Package.swift Resources Sources -type f ! -name '.DS_Store' | LC_ALL=C sort | xargs shasum -a 256 | shasum -a 256 | awk '{print $1}'
) > "$STAGE/Contents/Resources/build-source-hash"

codesign --force --deep --sign - "$STAGE"
codesign --verify --deep --strict "$STAGE"

if [[ -e "$APP" ]]; then
    /usr/bin/pgrep -f "^$APP/Contents/MacOS/JaegerShell" >/dev/null && { echo "Refusing to replace a running shell at $APP" >&2; exit 1; }
    PREVIOUS="$ROOT/previous/$(date +%Y%m%d-%H%M%S)-$$"
    mkdir -p "$PREVIOUS"
    mv "$APP" "$PREVIOUS/JaegerAI.app"
fi
mv "$STAGE" "$APP"

if [[ -n "$INSTALL_TARGET" ]]; then
    if [[ -e "$INSTALL_TARGET" ]]; then
        /usr/bin/pgrep -f "^$INSTALL_TARGET/Contents/MacOS/JaegerShell" >/dev/null && { echo "Refusing to replace a running shell at $INSTALL_TARGET" >&2; exit 1; }
        INSTALL_BACKUP="$ROOT/previous/$(date +%Y%m%d-%H%M%S)-$$-installed"
        mkdir -p "$INSTALL_BACKUP"
        mv "$INSTALL_TARGET" "$INSTALL_BACKUP/$(basename "$INSTALL_TARGET")"
    fi
    ditto "$APP" "$INSTALL_TARGET"
    codesign --force --deep --sign - "$INSTALL_TARGET"
    codesign --verify --deep --strict "$INSTALL_TARGET"
    plutil -lint "$INSTALL_TARGET/Contents/Info.plist" >/dev/null
    echo "$INSTALL_TARGET"
else
    echo "$APP"
fi
