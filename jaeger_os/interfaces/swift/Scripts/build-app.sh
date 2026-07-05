#!/usr/bin/env bash
#
# build-app.sh — assemble a real .app bundle from the SwiftPM
# executable.  Produces ``apps/JaegerOS/.build/JaegerOS.app`` ready
# to launch via ``open``.
#
# Why a build script vs. a real Xcode project: SwiftPM gives us
# fast incremental builds, a single Package.swift to read, no
# binary ``.xcodeproj`` to track.  An Xcode project adds tooling we
# don't need yet.  When code signing + notarisation become real
# concerns (App Store submission, distribution outside our laptops)
# we can switch to an Xcode project with this script as the
# fallback path.
#
# What this script does, in order:
#   1. swift build (debug by default, -c release with --release)
#   2. Generate AppIcon.icns from the jaeger_app_icon_* PNGs in
#      jaeger_os/assets/ (cached if AppIcon.icns is newer than its
#      input PNGs)
#   3. Build the .app skeleton:
#        JaegerOS.app/
#        ├── Contents/
#        │   ├── Info.plist
#        │   ├── MacOS/JaegerOS         (the executable)
#        │   └── Resources/
#        │       ├── AppIcon.icns
#        │       └── JaegerOS_JaegerOS.bundle/  (SPM resources)
#   4. Print the bundle path so the caller can open it
#
# Usage:
#   apps/JaegerOS/Scripts/build-app.sh           # debug
#   apps/JaegerOS/Scripts/build-app.sh --release # release

set -euo pipefail

CONFIG="debug"
INSTALL=0
for arg in "$@"; do
    case "$arg" in
        --release) CONFIG="release" ;;
        --install) INSTALL=1; CONFIG="release" ;;   # installs are always release
    esac
done

# Resolve paths — APP_ROOT is jaeger_os/interfaces/swift, REPO_ROOT is the
# JROS root (three levels up: swift → interfaces → jaeger_os → JROS).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$APP_ROOT/../../.." && pwd)"
BUILD_DIR="$APP_ROOT/.build"
ASSETS_DIR="$REPO_ROOT/jaeger_os/assets"

# Step 1 — Swift build.
echo "[build-app] swift build -c $CONFIG"
cd "$APP_ROOT"
swift build -c "$CONFIG"

# Locate the built executable.  SwiftPM puts it under
# .build/<triple>/<config>/<name>; on Apple Silicon the triple is
# arm64-apple-macosx.
SWIFT_BIN="$(swift build -c "$CONFIG" --show-bin-path)/JaegerOS"
if [[ ! -x "$SWIFT_BIN" ]]; then
    echo "[build-app] ERROR — built executable not found at $SWIFT_BIN" >&2
    exit 1
fi

# Step 2 — Generate AppIcon.icns from PNG set.
# iconutil wants a .iconset directory with specific filenames.
# Source PNGs live in jaeger_os/assets/ — see the README there.
ICONSET_TMP="$BUILD_DIR/AppIcon.iconset"
ICNS_PATH="$BUILD_DIR/AppIcon.icns"

icon_needs_rebuild() {
    [[ ! -f "$ICNS_PATH" ]] && return 0
    for size in 16 32 64 128 256 512; do
        local src="$ASSETS_DIR/jaeger_app_icon_${size}.png"
        if [[ -f "$src" && "$src" -nt "$ICNS_PATH" ]]; then
            return 0
        fi
    done
    return 1
}

if icon_needs_rebuild; then
    echo "[build-app] generating AppIcon.icns"
    rm -rf "$ICONSET_TMP"
    mkdir -p "$ICONSET_TMP"
    # Standard iconutil sizes — Apple's iconset naming convention.
    cp "$ASSETS_DIR/jaeger_app_icon_16.png"  "$ICONSET_TMP/icon_16x16.png"
    cp "$ASSETS_DIR/jaeger_app_icon_32.png"  "$ICONSET_TMP/icon_16x16@2x.png"
    cp "$ASSETS_DIR/jaeger_app_icon_32.png"  "$ICONSET_TMP/icon_32x32.png"
    cp "$ASSETS_DIR/jaeger_app_icon_64.png"  "$ICONSET_TMP/icon_32x32@2x.png"
    cp "$ASSETS_DIR/jaeger_app_icon_128.png" "$ICONSET_TMP/icon_128x128.png"
    cp "$ASSETS_DIR/jaeger_app_icon_256.png" "$ICONSET_TMP/icon_128x128@2x.png"
    cp "$ASSETS_DIR/jaeger_app_icon_256.png" "$ICONSET_TMP/icon_256x256.png"
    cp "$ASSETS_DIR/jaeger_app_icon_512.png" "$ICONSET_TMP/icon_256x256@2x.png"
    cp "$ASSETS_DIR/jaeger_app_icon_512.png" "$ICONSET_TMP/icon_512x512.png"
    if [[ -f "$ASSETS_DIR/jaeger_app_icon.png" ]]; then
        cp "$ASSETS_DIR/jaeger_app_icon.png" "$ICONSET_TMP/icon_512x512@2x.png"
    else
        cp "$ASSETS_DIR/jaeger_app_icon_512.png" "$ICONSET_TMP/icon_512x512@2x.png"
    fi
    iconutil -c icns -o "$ICNS_PATH" "$ICONSET_TMP"
    rm -rf "$ICONSET_TMP"
fi

# Step 3 — Assemble the .app bundle.
APP_BUNDLE="$BUILD_DIR/JaegerOS.app"
echo "[build-app] assembling $APP_BUNDLE"

rm -rf "$APP_BUNDLE"
mkdir -p "$APP_BUNDLE/Contents/MacOS"
mkdir -p "$APP_BUNDLE/Contents/Resources"

# Info.plist — copy from Resources/ (the canonical source), then stamp
# the REAL version: CFBundleShortVersionString from jaeger_os.__version__
# (the single source of truth), CFBundleVersion suffixed with the git SHA
# so two builds of the same release line are distinguishable.
cp "$APP_ROOT/Resources/Info.plist" "$APP_BUNDLE/Contents/Info.plist"
JROS_VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$REPO_ROOT/jaeger_os/__init__.py")"
GIT_SHA="$(git -C "$REPO_ROOT" rev-parse --short HEAD 2>/dev/null || echo dev)"
if [[ -n "$JROS_VERSION" ]]; then
    /usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $JROS_VERSION" \
        -c "Set :CFBundleVersion $JROS_VERSION+$GIT_SHA" \
        "$APP_BUNDLE/Contents/Info.plist"
fi

# Executable.
cp "$SWIFT_BIN" "$APP_BUNDLE/Contents/MacOS/JaegerOS"
chmod +x "$APP_BUNDLE/Contents/MacOS/JaegerOS"

# Icon.
cp "$ICNS_PATH" "$APP_BUNDLE/Contents/Resources/AppIcon.icns"

# SPM resource bundle (jaeger_icon_22.png etc.).  SwiftPM puts it
# next to the executable in the build dir; the .app needs it in
# Contents/Resources next to the binary AND we need to make sure
# Bundle.module can find it at runtime.  SwiftPM's resolution looks
# for the bundle relative to the executable, so copying it next to
# the binary in MacOS/ keeps the resource path correct.
SPM_BUNDLE_NAME="JaegerOS_JaegerOS.bundle"
SPM_BUNDLE_SRC="$(dirname "$SWIFT_BIN")/$SPM_BUNDLE_NAME"
if [[ -d "$SPM_BUNDLE_SRC" ]]; then
    DEST_BUNDLE="$APP_BUNDLE/Contents/MacOS/$SPM_BUNDLE_NAME"
    cp -R "$SPM_BUNDLE_SRC" "$DEST_BUNDLE"
    # SPM emits the resource bundle as a bare directory — no
    # Info.plist.  codesign --deep refuses to sign a "bundle" without
    # an Info.plist, so we drop a minimal stub in.  Bundle.module
    # finds resources by path, not by Info.plist contents — adding
    # this is purely to satisfy the signer.
    cat > "$DEST_BUNDLE/Info.plist" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleIdentifier</key>
    <string>com.jenkinsrobotics.JaegerOS.resources</string>
    <key>CFBundleName</key>
    <string>JaegerOS Resources</string>
    <key>CFBundlePackageType</key>
    <string>BNDL</string>
</dict>
</plist>
EOF
fi

# Ad-hoc code-sign with the new entitlements (required on Apple
# Silicon for TCC prompts to actually fire — an unsigned app's
# Info.plist privacy strings get ignored).  Sign inner bundles
# first, then the outer .app, since codesign needs each contained
# bundle to be valid before the outer signature is computed.
# Signing.  Default: ad-hoc (dev builds — TCC prompts fire, no Gatekeeper
# story).  Distribution: export JAEGER_SIGN_IDENTITY="Developer ID
# Application: <name> (<team>)" for a real signature; then notarize with
#   xcrun notarytool submit <zip> --keychain-profile jaeger-notary --wait
#   xcrun stapler staple JaegerOS.app
SIGN_IDENTITY="${JAEGER_SIGN_IDENTITY:--}"
echo "[build-app] codesign (identity: ${SIGN_IDENTITY})"
codesign --force --sign "$SIGN_IDENTITY" \
    "$APP_BUNDLE/Contents/MacOS/$SPM_BUNDLE_NAME" 2>/dev/null || true
codesign --force --options runtime --sign "$SIGN_IDENTITY" "$APP_BUNDLE" 2>&1 || \
    echo "[build-app] WARN — codesign failed (continuing; mic prompt may not fire)"

if [[ "$INSTALL" == "1" ]]; then
    echo "[build-app] installing -> /Applications/JaegerOS.app"
    rm -rf "/Applications/JaegerOS.app"
    ditto "$APP_BUNDLE" "/Applications/JaegerOS.app"
fi

echo "$APP_BUNDLE"
