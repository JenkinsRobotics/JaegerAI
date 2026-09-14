#!/usr/bin/env bash
#
# build-app.sh — assemble a real .app bundle from the SwiftPM
# executable. Produces an external-cache ``JaegerAI.app`` ready
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
#      jaeger_ai/assets/ (cached if AppIcon.icns is newer than its
#      input PNGs)
#   3. Build the .app skeleton:
#        JaegerAI.app/
#        ├── Contents/
#        │   ├── Info.plist
#        │   ├── MacOS/JaegerAI         (the executable)
#        │   └── Resources/
#        │       ├── AppIcon.icns
#        │       └── JaegerAI_JaegerAI.bundle/  (SPM resources)
#   4. Print the bundle path so the caller can open it
#
# Usage:
#   apps/JaegerAI/Scripts/build-app.sh           # debug
#   apps/JaegerAI/Scripts/build-app.sh --release # release

set -euo pipefail

CONFIG="debug"
INSTALL=0
DISTRIBUTION=0
for arg in "$@"; do
    case "$arg" in
        --release) CONFIG="release" ;;
        --install) INSTALL=1; CONFIG="release" ;;   # installs are always release
        --dev)     ;;   # accepted for compat — debug config (the default)
        --distribution) DISTRIBUTION=1; CONFIG="release" ;;
        *) echo "Unknown build argument: $arg" >&2; exit 2 ;;
    esac
done

SIGN_IDENTITY="${JAEGER_SIGN_IDENTITY:--}"
if [[ "$DISTRIBUTION" == "1" && "$SIGN_IDENTITY" != "Developer ID Application:"* ]]; then
    echo "Distribution requires JAEGER_SIGN_IDENTITY with a Developer ID Application certificate." >&2
    exit 2
fi

# ONE app (operator call 2026-07-14, ending the 2026-07-05 two-app
# split): dev is a launch STATE, not a separate bundle. `jaeger dev`
# runs this same JaegerAI.app against the repo's jaeger-dev instance via
# the environment it launches with; a separate JaegerAI-dev.app meant a
# second bundle id, and macOS TCC keys permission grants on bundle id —
# every permission had to be granted twice. `--dev` is still accepted
# (dev-checkout builds pass it) but only means "debug config" now.
APP_NAME="JaegerAI"

# Resolve paths — APP_ROOT is the Swift package, REPO_ROOT the JaegerAI checkout.
#
# REPO_ROOT is found by walking up to the directory that actually holds
# jaeger_ai/__init__.py rather than counting "..". The app is reachable by two
# paths of different depths — jaeger_ai/interfaces/swift (the real one) and the
# apps/macos symlink that aliases it — and `cd`+`pwd` resolves the symlink, so
# any fixed count is right for one spelling and wrong for the other. Counting
# from apps/macos landed REPO_ROOT on jaeger_ai/ and the version lookup then
# read jaeger_ai/jaeger_ai/__init__.py, which does not exist.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$APP_ROOT"
while [[ "$REPO_ROOT" != "/" && ! -f "$REPO_ROOT/jaeger_ai/__init__.py" ]]; do
  REPO_ROOT="$(dirname "$REPO_ROOT")"
done
if [[ ! -f "$REPO_ROOT/jaeger_ai/__init__.py" ]]; then
  echo "[build-app] cannot locate the JaegerAI checkout above $APP_ROOT" >&2
  exit 1
fi
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPYCACHEPREFIX="${PYTHONPYCACHEPREFIX:-$HOME/.cache/jaeger/pycache}"
BUILD_PYTHON="${JAEGER_VENV:-$HOME/.jaeger/venv}/bin/python"
if [[ ! -x "$BUILD_PYTHON" ]]; then
    echo "[build-app] ERROR — install Python packages first, or set JAEGER_VENV ($BUILD_PYTHON missing)" >&2
    exit 1
fi
BUILD_DIR="$("$BUILD_PYTHON" "$REPO_ROOT/jaeger_ai/core/native_app.py" "$REPO_ROOT")"
ASSETS_DIR="$REPO_ROOT/jaeger_ai/assets"

# Step 1 — Swift build.
echo "[build-app] swift build -c $CONFIG"
cd "$APP_ROOT"
swift build -c "$CONFIG" --scratch-path "$BUILD_DIR"

# Locate the built executable.  SwiftPM puts it under
# .build/<triple>/<config>/<name>; on Apple Silicon the triple is
# arm64-apple-macosx.
SWIFT_BIN="$(swift build -c "$CONFIG" --scratch-path "$BUILD_DIR" --show-bin-path)/JaegerAI"
if [[ ! -x "$SWIFT_BIN" ]]; then
    echo "[build-app] ERROR — built executable not found at $SWIFT_BIN" >&2
    exit 1
fi

# Step 2 — Generate AppIcon.icns from PNG set.
# iconutil wants a .iconset directory with specific filenames.
# Source PNGs live in jaeger_ai/assets/ — see the README there.
ICONSET_TMP="$BUILD_DIR/AppIcon.iconset"
ICNS_PATH="$BUILD_DIR/AppIcon.icns"

icon_needs_rebuild() {
    [[ ! -f "$ICNS_PATH" ]] && return 0
    [[ "$ASSETS_DIR/jaeger_app_icon.png" -nt "$ICNS_PATH" ]] && return 0
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
APP_BUNDLE="$BUILD_DIR/$APP_NAME.app"
echo "[build-app] assembling $APP_BUNDLE"

rm -rf "$APP_BUNDLE"
mkdir -p "$APP_BUNDLE/Contents/MacOS"
mkdir -p "$APP_BUNDLE/Contents/Resources"

# Info.plist — copy from Resources/ (the canonical source), then stamp
# the REAL version: CFBundleShortVersionString from jaeger_ai.__version__
# (the single source of truth), CFBundleVersion suffixed with the git SHA
# so two builds of the same release line are distinguishable.
cp "$APP_ROOT/Resources/Info.plist" "$APP_BUNDLE/Contents/Info.plist"
JaegerAI_VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$REPO_ROOT/jaeger_ai/__init__.py")"
GIT_SHA="$(git -C "$REPO_ROOT" rev-parse --short HEAD 2>/dev/null || echo dev)"
if [[ -n "$JaegerAI_VERSION" ]]; then
    /usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $JaegerAI_VERSION" \
        -c "Set :CFBundleVersion $JaegerAI_VERSION+$GIT_SHA" \
        "$APP_BUNDLE/Contents/Info.plist"
fi
# One-app collapse (2026-07-14): clear out a pre-collapse dev bundle so
# a stale JaegerAI-dev.app can't linger next to the real one.
rm -rf "$BUILD_DIR/JaegerAI-dev.app"

# Executable.
cp "$SWIFT_BIN" "$APP_BUNDLE/Contents/MacOS/JaegerAI"
chmod +x "$APP_BUNDLE/Contents/MacOS/JaegerAI"

# The Qt face must execute inside THIS app bundle. Launching an external Python
# leaves NSBundle.main without privacy strings, so Qt refuses camera consent.
# Reuse the development environment's interpreter and site packages; this is
# still a repo-backed development app, not a self-contained Python distribution.
cp -L "$BUILD_PYTHON" "$APP_BUNDLE/Contents/MacOS/JaegerMultimodal"
chmod +x "$APP_BUNDLE/Contents/MacOS/JaegerMultimodal"
JAEGER_PYTHON_BASE="$("$BUILD_PYTHON" -c 'import sys; print(sys.base_prefix)')"
JAEGER_PYTHON_SITE="$("$BUILD_PYTHON" -c 'import sysconfig; print(sysconfig.get_path("purelib"))')"
/usr/libexec/PlistBuddy -c "Add :JaegerPythonHome string $JAEGER_PYTHON_BASE" \
    -c "Add :JaegerPythonSite string $JAEGER_PYTHON_SITE" \
    -c "Add :JaegerLauncher string $(dirname "$BUILD_PYTHON")/jaeger" \
    -c "Add :JaegerInstallRoot string $REPO_ROOT" \
    -c "Add :JaegerVenv string $(dirname "$(dirname "$BUILD_PYTHON")")" \
    "$APP_BUNDLE/Contents/Info.plist"

# Icon.
cp "$ICNS_PATH" "$APP_BUNDLE/Contents/Resources/AppIcon.icns"

# SPM resource bundle (jaeger_icon_22.png etc.).  SwiftPM puts it
# next to the executable in the build dir; the .app needs it in
# Contents/Resources next to the binary AND we need to make sure
# Bundle.module can find it at runtime. Xcode 27 resolves application package
# resources below Contents/Resources.
SPM_BUNDLE_NAME="JaegerAI_JaegerAI.bundle"
SPM_BUNDLE_SRC="$(dirname "$SWIFT_BIN")/$SPM_BUNDLE_NAME"
DEST_BUNDLE="$APP_BUNDLE/Contents/Resources/$SPM_BUNDLE_NAME"
if [[ -d "$SPM_BUNDLE_SRC" ]]; then
    cp -R "$SPM_BUNDLE_SRC" "$DEST_BUNDLE"
    # Older SwiftPM versions emitted a bare resource directory. Xcode 27 emits
    # a standard Contents/Info.plist bundle; adding a second plist at the root
    # makes codesign reject it as unsealed content. Supply the compatibility
    # plist only when SwiftPM did not generate either layout.
    if [[ ! -f "$DEST_BUNDLE/Info.plist" && ! -f "$DEST_BUNDLE/Contents/Info.plist" ]]; then
        cat > "$DEST_BUNDLE/Info.plist" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleIdentifier</key>
    <string>com.jenkinsrobotics.JaegerAI.resources</string>
    <key>CFBundleName</key>
    <string>JaegerAI Resources</string>
    <key>CFBundlePackageType</key>
    <string>BNDL</string>
</dict>
</plist>
EOF
    fi
else
    echo "[build-app] ERROR — SwiftPM resource bundle missing at $SPM_BUNDLE_SRC" >&2
    exit 1
fi

# OS 1 utility intelligence. This model is part of the product runtime, not
# operator state: it must be available before Ollama, credentials, or a main
# agent model exists. Development builds may omit it (manual setup remains
# available); release/install builds fail rather than publishing an app that
# claims offline onboarding but downloads weights on first launch.
SYSTEM_MODEL_FILENAME="Qwen_Qwen3-1.7B-Q4_K_M.gguf"
SYSTEM_MODEL_SHA256="72c5c3cb38fa32d5256e2fe30d03e7a64c6c79e668ad84057e3bd66e250b24fb"
SYSTEM_MODEL_SOURCE="${JAEGER_SYSTEM_MODEL:-$HOME/.jaeger/models/qwen3-1.7b-system-q4_k_m/$SYSTEM_MODEL_FILENAME}"
if [[ -f "$SYSTEM_MODEL_SOURCE" ]]; then
    ACTUAL_SYSTEM_MODEL_SHA256="$(shasum -a 256 "$SYSTEM_MODEL_SOURCE" | awk '{print $1}')"
    if [[ "$ACTUAL_SYSTEM_MODEL_SHA256" != "$SYSTEM_MODEL_SHA256" ]]; then
        echo "[build-app] ERROR — OS utility model checksum mismatch" >&2
        exit 1
    fi
    mkdir -p "$APP_BUNDLE/Contents/Resources/Models"
    cp "$SYSTEM_MODEL_SOURCE" "$APP_BUNDLE/Contents/Resources/Models/$SYSTEM_MODEL_FILENAME"
elif [[ "$CONFIG" == "release" ]]; then
    echo "[build-app] ERROR — release requires bundled OS utility model at $SYSTEM_MODEL_SOURCE" >&2
    exit 1
else
    echo "[build-app] WARN — utility model absent; conversational setup unavailable" >&2
fi

# The setup guide and the created agent use the same neural speech model
# with different voice packs. Package the exact Kokoro revision and three
# voices required by that handoff so a clean, offline Mac never falls back
# to the legacy system synthesizer.
KOKORO_REVISION="f3ff3571791e39611d31c381e3a41a3af07b4987"
KOKORO_SOURCE="${JAEGER_KOKORO_ASSETS:-$HOME/.cache/huggingface/hub/models--hexgrad--Kokoro-82M/snapshots/$KOKORO_REVISION}"
KOKORO_DEST="$APP_BUNDLE/Contents/Resources/Kokoro"
if [[ -f "$KOKORO_SOURCE/config.json" && -f "$KOKORO_SOURCE/kokoro-v1_0.pth" ]]; then
    mkdir -p "$KOKORO_DEST/voices"
    cp -L "$KOKORO_SOURCE/config.json" "$KOKORO_DEST/config.json"
    cp -L "$KOKORO_SOURCE/kokoro-v1_0.pth" "$KOKORO_DEST/kokoro-v1_0.pth"
    for voice in am_adam am_michael af_heart; do
        cp -L "$KOKORO_SOURCE/voices/$voice.pt" "$KOKORO_DEST/voices/$voice.pt"
    done
elif [[ "$CONFIG" == "release" ]]; then
    echo "[build-app] ERROR — release requires bundled Kokoro assets at $KOKORO_SOURCE" >&2
    exit 1
else
    echo "[build-app] WARN — Kokoro assets absent; setup voice unavailable offline" >&2
fi

# Stamp the bundle with the commit it was built from — update/launch paths
# compare this against the Swift tree to decide staleness (rebuilds keyed to
# "what did this pull change" miss manual pulls and failed builds). Must be
# written BEFORE codesign: adding a file afterwards invalidates the signature.
git -C "$REPO_ROOT" rev-parse HEAD > "$APP_BUNDLE/Contents/Resources/build-commit" 2>/dev/null || true

# Ad-hoc code-sign with the new entitlements (required on Apple
# Silicon for TCC prompts to actually fire — an unsigned app's
# Info.plist privacy strings get ignored).  Sign inner bundles
# first, then the outer .app, since codesign needs each contained
# bundle to be valid before the outer signature is computed.
# Signing.  Default: ad-hoc (dev builds — TCC prompts fire, no Gatekeeper
# story).  Distribution: export JAEGER_SIGN_IDENTITY="Developer ID
# Application: <name> (<team>)" for a real signature; then notarize with
#   xcrun notarytool submit <zip> --keychain-profile jaeger-notary --wait
#   xcrun stapler staple JaegerAI.app
SIGN_IDENTITY="${JAEGER_SIGN_IDENTITY:--}"
echo "[build-app] codesign (identity: ${SIGN_IDENTITY})"
codesign --force --sign "$SIGN_IDENTITY" "$DEST_BUNDLE"
if [[ -d "$APP_BUNDLE/Contents/MacOS/$SPM_BUNDLE_NAME" ]]; then
    codesign --force --sign "$SIGN_IDENTITY" \
        "$APP_BUNDLE/Contents/MacOS/$SPM_BUNDLE_NAME"
fi
codesign --force --options runtime --entitlements \
    "$APP_ROOT/Resources/JaegerMultimodal.entitlements" \
    --sign "$SIGN_IDENTITY" "$APP_BUNDLE/Contents/MacOS/JaegerMultimodal"
codesign --force --options runtime --entitlements \
    "$APP_ROOT/Resources/JaegerAI.entitlements" \
    --sign "$SIGN_IDENTITY" "$APP_BUNDLE"
codesign --verify --deep --strict "$APP_BUNDLE"

# Keep the app VISIBLE at the repo root (gitignored symlink) — the
# bundle itself lives in the external build cache.
# (One-app collapse 2026-07-14: also drop the old dev-shell symlink.)
rm -f "$REPO_ROOT/JaegerAI-dev.app"
ln -sfn "$APP_BUNDLE" "$REPO_ROOT/JaegerAI.app"

if [[ "$INSTALL" == "1" ]]; then
    echo "[build-app] installing -> /Applications/Jaeger AI.app"
    "$BUILD_PYTHON" - "$REPO_ROOT" "$APP_BUNDLE" <<'PY'
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from jaeger_ai.cli.verbs.launcher_verb import _install_native_bundle
from jaeger_ai.core.instance.instance import operator_state_root
_install_native_bundle(Path(sys.argv[2]), Path("/Applications/Jaeger AI.app"),
                       operator_state_root() / "launcher-backups")
PY
fi

echo "$APP_BUNDLE"
