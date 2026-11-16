#!/usr/bin/env bash
# Build Jaeger PIM (EventKit/Contacts helper) into ~/.jaeger/bin/JaegerPIM.app (ad-hoc signed).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="${JAEGER_PIM_APP:-$HOME/.jaeger/bin/JaegerPIM.app}"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
swiftc -O -o "$TMP/JaegerPIM" "$HERE/main.swift" -framework EventKit -framework Contacts
mkdir -p "$TMP/JaegerPIM.app/Contents/MacOS"
cp "$HERE/Info.plist" "$TMP/JaegerPIM.app/Contents/Info.plist"
cp "$TMP/JaegerPIM" "$TMP/JaegerPIM.app/Contents/MacOS/JaegerPIM"
codesign --force --sign - "$TMP/JaegerPIM.app"
mkdir -p "$(dirname "$OUT")"; rm -rf "$OUT.new"; cp -R "$TMP/JaegerPIM.app" "$OUT.new"
[[ -d "$OUT" ]] && mv "$OUT" "$OUT.old.$$"; mv "$OUT.new" "$OUT"; rm -rf "$OUT".old.*
echo "$OUT"
