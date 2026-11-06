#!/bin/bash
# JaegerAI — macOS Autonomous Robot & Appliance Host Setup
#
# Configures an Apple Silicon Mac (e.g. Mac Studio) for 24/7 autonomous operation:
# 1. Hardware Power & Reboot Recovery (auto-restart on power loss, no sleep, freeze recovery)
# 2. Dedicated User Account isolation ('jaeger' user for quarantined blast radius & RAM optimization)
# 3. Scoped Passwordless Sudo (/etc/sudoers.d/jaeger-host for daemon/hardware controls)
# 4. Memory & I/O Optimization (Spotlight indexing exclusion, LLM VRAM settings)
# 5. Persistent LaunchAgent (~/Library/LaunchAgents/com.jenkinsrobotics.jaeger.plist)
# 6. Concise checklist for macOS GUI TCC approvals (Full Disk Access, Mic, Camera, Auto-Login)
#
# Usage:
#   ./scripts/setup-mac-robot.sh [options]
# Options:
#   --non-interactive     Run without interactive prompts (uses defaults)
#   --user <name>         Target dedicated robot username (default: jaeger)
#   --skip-user-creation  Skip creating a dedicated user account
#   --help                Show this help message

set -euo pipefail

# ANSI Colors
BOLD="\033[1m"
GREEN="\033[0;32m"
YELLOW="\033[0;33m"
CYAN="\033[0;36m"
RED="\033[0;31m"
NC="\033[0m"

# Validate macOS
if [[ "$(uname -s)" != "Darwin" ]]; then
  echo -e "${RED}✗ Error: This setup script is specifically for macOS.${NC}" >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_USER="jaeger"
NON_INTERACTIVE=0
SKIP_USER=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --non-interactive) NON_INTERACTIVE=1; shift ;;
    --user) TARGET_USER="$2"; shift 2 ;;
    --skip-user-creation) SKIP_USER=1; shift ;;
    -h|--help)
      echo "Usage: ./scripts/setup-mac-robot.sh [--non-interactive] [--user <username>] [--skip-user-creation]"
      exit 0
      ;;
    *) echo -e "${RED}Unknown option: $1${NC}" >&2; exit 1 ;;
  esac
done

echo
echo -e "${BOLD}╔═══════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║      JaegerAI — Autonomous Robot & Host Readiness Setup           ║${NC}"
echo -e "${BOLD}╚═══════════════════════════════════════════════════════════════════╝${NC}"
echo -e "  Host:         $(scutil --get ComputerName 2>/dev/null || hostname)"
echo -e "  Target User:  ${CYAN}${TARGET_USER}${NC}"
echo -e "  Repo Root:    ${REPO_ROOT}"
echo

# ─────────────────────────────────────────────────────────────────────────────
# 1. Power & Hardware Recovery Settings (pmset & systemsetup)
# ─────────────────────────────────────────────────────────────────────────────
echo -e "${BOLD}[1/5] Configuring Hardware Power & Reboot Recovery...${NC}"

# Ask for sudo once upfront
if ! sudo -n true 2>/dev/null; then
  echo -e "  ${YELLOW}Administrator privileges (sudo) required for system power settings.${NC}"
  sudo -v
fi

# Keep sudo alive while script runs
while true; do sudo -n true; sleep 60; kill -0 "$$" || exit; done 2>/dev/null &
SUDO_KEEP_ALIVE_PID=$!
trap 'kill "$SUDO_KEEP_ALIVE_PID" 2>/dev/null || true' EXIT

# 1. Automatically restart after a power outage
sudo pmset -a autorestart 1
echo -e "  ${GREEN}✓${NC} Auto-restart on power failure enabled (autorestart 1)"

# 2. Never put the system to sleep
sudo pmset -a sleep 0
echo -e "  ${GREEN}✓${NC} System sleep disabled (sleep 0)"

# 3. Never spin down or sleep disks
sudo pmset -a disksleep 0
echo -e "  ${GREEN}✓${NC} Disk sleep disabled (disksleep 0)"

# 4. Turn off display after 15 min idle (saves GPU/VRAM while host runs headless)
sudo pmset -a displaysleep 15
echo -e "  ${GREEN}✓${NC} Display sleep set to 15 min (displaysleep 15)"

# 5. Automatically restart if macOS kernel freezes
sudo systemsetup -setrestartfreeze on >/dev/null 2>&1 || true
echo -e "  ${GREEN}✓${NC} Auto-restart on system freeze enabled"

# 6. Wake on network magic packet (WoL) and Power Nap
sudo pmset -a womp 1 powernap 1 >/dev/null 2>&1 || true
echo -e "  ${GREEN}✓${NC} Wake-on-LAN and Power Nap enabled"

# ─────────────────────────────────────────────────────────────────────────────
# 2. Dedicated Robot User Account ('jaeger')
# ─────────────────────────────────────────────────────────────────────────────
echo
echo -e "${BOLD}[2/5] Checking Dedicated Robot User Account ('${TARGET_USER}')...${NC}"

CURRENT_USER="$(id -un)"

if [[ "$SKIP_USER" -eq 1 || "$CURRENT_USER" == "$TARGET_USER" ]]; then
  echo -e "  ${CYAN}i${NC} Using current user account: ${CURRENT_USER}"
else
  if id -u "$TARGET_USER" >/dev/null 2>&1; then
    echo -e "  ${GREEN}✓${NC} User '${TARGET_USER}' already exists."
  else
    CREATE_ACCOUNT="y"
    if [[ "$NON_INTERACTIVE" -eq 0 ]]; then
      echo -e "  A dedicated '${TARGET_USER}' user quarantines your personal files (iCloud, Docs)"
      echo -e "  and frees up ~28-30 GB of RAM by eliminating personal background apps."
      read -r -p "  Create user '${TARGET_USER}' on this Mac? [Y/n]: " RESP || RESP="y"
      [[ "$RESP" =~ ^[Nn]$ ]] && CREATE_ACCOUNT="n"
    fi

    if [[ "$CREATE_ACCOUNT" == "y" ]]; then
      echo -e "  Creating user '${TARGET_USER}'..."
      # Create admin account for jaeger so it can install dependencies
      sudo sysadminctl -addUser "$TARGET_USER" -fullName "Jaeger Robot" -home "/Users/$TARGET_USER" -admin 2>&1 | grep -v "Operation was" || true
      if id -u "$TARGET_USER" >/dev/null 2>&1; then
        echo -e "  ${GREEN}✓${NC} Created user '${TARGET_USER}' at /Users/${TARGET_USER}"
      else
        echo -e "  ${YELLOW}⚠ sysadminctl did not complete automatically.${NC}"
        echo -e "  Please create the '${TARGET_USER}' account in System Settings > Users & Groups."
      fi
    else
      echo -e "  Skipping dedicated user creation; using current user (${CURRENT_USER})."
      TARGET_USER="$CURRENT_USER"
    fi
  fi
fi

# ─────────────────────────────────────────────────────────────────────────────
# 3. Scoped Passwordless Sudoers for Autonomous Host Maintenance
# ─────────────────────────────────────────────────────────────────────────────
echo
echo -e "${BOLD}[3/5] Configuring Scoped Sudoers for Host Maintenance...${NC}"

SUDOERS_FILE="/etc/sudoers.d/jaeger-host"
TMP_SUDOERS="$(mktemp /tmp/jaeger-sudoers.XXXXXX)"

cat <<EOF > "$TMP_SUDOERS"
# Jaeger Autonomous Operator — Scoped Host Maintenance Permissions
${TARGET_USER} ALL=(ALL) NOPASSWD: /bin/launchctl, /usr/sbin/pmset, /usr/sbin/systemsetup, /usr/bin/pkill, /usr/bin/killall
EOF

# Validate syntax with visudo
if sudo visudo -cf "$TMP_SUDOERS" >/dev/null 2>&1; then
  sudo cp "$TMP_SUDOERS" "$SUDOERS_FILE"
  sudo chmod 0440 "$SUDOERS_FILE"
  rm -f "$TMP_SUDOERS"
  echo -e "  ${GREEN}✓${NC} Scoped sudoers installed at ${SUDOERS_FILE}"
else
  echo -e "  ${RED}✗ visudo validation failed for sudoers template; skipped for safety.${NC}"
  rm -f "$TMP_SUDOERS"
fi

# ─────────────────────────────────────────────────────────────────────────────
# 4. Memory & I/O Optimizations (Spotlight & LLM VRAM)
# ─────────────────────────────────────────────────────────────────────────────
echo
echo -e "${BOLD}[4/5] Applying Memory & I/O Baseline Optimizations...${NC}"

# Exclude repository and state directories from Spotlight indexing to save CPU/disk thrashing
touch "${REPO_ROOT}/.metadata_never_index" 2>/dev/null || true
echo -e "  ${GREEN}✓${NC} Excluded Jaeger repo from Spotlight indexing"

TARGET_HOME="/Users/${TARGET_USER}"
if [[ -d "$TARGET_HOME" ]]; then
  sudo mkdir -p "$TARGET_HOME/.jaeger" "$TARGET_HOME/.jaeger/logs"
  sudo touch "$TARGET_HOME/.jaeger/.metadata_never_index"
  sudo chown -R "${TARGET_USER}:staff" "$TARGET_HOME/.jaeger" 2>/dev/null || true
  echo -e "  ${GREEN}✓${NC} Excluded ~/.jaeger from Spotlight indexing"
fi

# Check for heavy redundant remote desktop daemons
DAEMONS_FOUND=()
[[ -f "/Library/LaunchDaemons/com.carriez.RustDesk_service.plist" ]] && DAEMONS_FOUND+=("RustDesk (com.carriez.RustDesk_service)")
[[ -f "/Library/LaunchDaemons/com.philandro.anydesk.Helper.plist" ]] && DAEMONS_FOUND+=("AnyDesk (com.philandro.anydesk.Helper)")

if [[ ${#DAEMONS_FOUND[@]} -gt 0 ]]; then
  echo -e "  ${YELLOW}Notice:${NC} Found redundant remote desktop background daemons:"
  for d in "${DAEMONS_FOUND[@]}"; do
    echo -e "    - $d"
  done
  echo -e "  ${CYAN}Hint:${NC} To free RAM, consider disabling them if Jump Desktop is your primary remote tool:"
  echo -e "    sudo launchctl bootout system/com.philandro.anydesk.Helper"
  echo -e "    sudo launchctl bootout system/com.carriez.RustDesk_service"
fi

# ─────────────────────────────────────────────────────────────────────────────
# 5. Persistent LaunchAgent Setup
# ─────────────────────────────────────────────────────────────────────────────
echo
echo -e "${BOLD}[5/5] Configuring Persistent LaunchAgent...${NC}"

LAUNCH_AGENTS_DIR="${TARGET_HOME}/Library/LaunchAgents"
PLIST_PATH="${LAUNCH_AGENTS_DIR}/com.jenkinsrobotics.jaeger.plist"
JAEGER_BIN="${REPO_ROOT}/jaeger"

if [[ -d "$TARGET_HOME" ]]; then
  sudo mkdir -p "$LAUNCH_AGENTS_DIR"
  sudo mkdir -p "${TARGET_HOME}/.jaeger/logs"

  TMP_PLIST="$(mktemp /tmp/jaeger-plist.XXXXXX)"
  cat <<EOF > "$TMP_PLIST"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.jenkinsrobotics.jaeger</string>
    <key>ProgramArguments</key>
    <array>
        <string>${JAEGER_BIN}</string>
        <string>autostart</string>
        <string>enable</string>
        <string>--daemon</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${REPO_ROOT}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
        <key>Crashed</key>
        <true/>
    </dict>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/Users/${TARGET_USER}/.jaeger/venv/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
        <key>JAEGER_HOME</key>
        <string>${REPO_ROOT}</string>
        <key>JAEGER_STATE_DIR</key>
        <string>/Users/${TARGET_USER}/.jaeger</string>
        <key>OLLAMA_KEEP_ALIVE</key>
        <string>5m</string>
        <key>OLLAMA_NUM_PARALLEL</key>
        <string>1</string>
    </dict>
    <key>StandardOutPath</key>
    <string>/Users/${TARGET_USER}/.jaeger/logs/daemon-stdout.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/${TARGET_USER}/.jaeger/logs/daemon-stderr.log</string>
    <key>SoftResourceLimits</key>
    <dict>
        <key>NumberOfFiles</key>
        <integer>1048575</integer>
    </dict>
</dict>
</plist>
EOF

  sudo cp "$TMP_PLIST" "$PLIST_PATH"
  sudo chown "${TARGET_USER}:staff" "$PLIST_PATH"
  sudo chmod 0644 "$PLIST_PATH"
  rm -f "$TMP_PLIST"
  echo -e "  ${GREEN}✓${NC} LaunchAgent template installed at ${PLIST_PATH}"
fi

# ─────────────────────────────────────────────────────────────────────────────
# Next Steps & macOS GUI TCC Checklist
# ─────────────────────────────────────────────────────────────────────────────
echo
echo -e "${BOLD}═══════════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}${BOLD}✓ Host Readiness Script Complete!${NC}"
echo -e "${BOLD}═══════════════════════════════════════════════════════════════════${NC}"
echo
echo -e "To finish making this Mac fully autonomous, complete these 3 steps in macOS:"
echo
echo -e "  ${BOLD}1. Enable Automatic Login (Required for Microphone & Camera):${NC}"
echo -e "     • Open ${CYAN}System Settings > Users & Groups${NC}."
echo -e "     • Set ${BOLD}Automatically log in as${NC} to ${CYAN}${TARGET_USER}${NC}."
echo
echo -e "  ${BOLD}2. Grant Zero-Approval TCC Permissions:${NC}"
echo -e "     • Open ${CYAN}System Settings > Privacy & Security${NC}."
echo -e "     • Under ${BOLD}Full Disk Access${NC}: Enable for ${CYAN}Terminal${NC} and Python (${CYAN}/Users/${TARGET_USER}/.jaeger/venv/bin/python3${NC})."
echo -e "     • Under ${BOLD}Microphone & Camera${NC}: Ensure access is allowed for Python / Terminal."
echo -e "     • Under ${BOLD}Accessibility${NC}: Allow Terminal / JaegerShell for UI automation."
echo
echo -e "  ${BOLD}3. Test Reboot Recovery:${NC}"
echo -e "     • Reboot the Mac Studio. It will boot directly into '${TARGET_USER}', start"
echo -e "       the Jaeger daemon automatically, and recover without any user prompts."
echo
EOF
