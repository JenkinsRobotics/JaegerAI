#!/bin/zsh
# Install / restart the Jaeger phone-channels relay (Telegram bot + iMessage self-chat).
set -euo pipefail
ROOT="${JAEGER_INSTALL_ROOT:-$HOME/GitHub/JaegerAI}"
STATE="${JAEGER_STATE_DIR:-$HOME/.jaeger}"
LABEL=com.jenkinsrobotics.jaeger-channels
PLIST="$STATE/launchd/$LABEL.plist"
mkdir -p "$STATE/launchd" "$STATE/logs" "$STATE/channels"
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$STATE/venv/bin/python</string><string>-u</string><string>-B</string>
    <string>-m</string><string>jaeger_ai.features.channels.relay</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>JAEGER_INSTALL_ROOT</key><string>$ROOT</string>
    <key>JAEGER_STATE_DIR</key><string>$STATE</string>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    <key>PYTHONPATH</key><string>$ROOT:$ROOT/packages/jaeger-agent:$ROOT/packages/jaeger-os</string>
    <key>PYTHONDONTWRITEBYTECODE</key><string>1</string>
    <key>PYTHONUNBUFFERED</key><string>1</string>
  </dict>
  <key>KeepAlive</key><true/>
  <key>RunAtLoad</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>StandardOutPath</key><string>$STATE/logs/channels.log</string>
  <key>StandardErrorPath</key><string>$STATE/logs/channels.log</string>
</dict>
</plist>
PL
UID_=$(id -u)
launchctl bootout "gui/$UID_/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$UID_" "$PLIST"
echo "installed $LABEL"
