"""``jaeger autostart`` — run a unit's agent unattended at boot/login.

Manual start is unchanged: ``jaeger`` still launches the agent directly.
``autostart`` *additionally* brings it up without anyone logging in — for a
deployed unit that should come back after a reboot or power loss. **Opt-in**
(a local LLM at every boot is heavy).

  * macOS → a LaunchAgent in ``~/Library/LaunchAgents/`` (starts at login)
  * Linux → a ``systemd --user`` unit in ``~/.config/systemd/user/`` plus
            linger so it starts at boot without an interactive login

``enable`` forwards any extra args to ``jaeger`` (e.g.
``jaeger autostart enable --tui``); the default is a bare ``jaeger`` — the same
surface you'd launch by hand.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_LABEL = "com.jenkinsrobotics.jaeger"   # launchd Label
_UNIT = "jaeger.service"                # systemd unit name

_USAGE = (
    "usage: jaeger autostart {enable|disable|status} [args forwarded to jaeger]\n"
    "\n"
    "  enable [args]  install + load a per-user boot/login service that runs\n"
    "                 `jaeger` (args, if any, are forwarded). Opt-in.\n"
    "  disable        unload + remove the service.\n"
    "  status         is autostart installed + running?\n"
    "\n"
    "  macOS → ~/Library/LaunchAgents LaunchAgent · Linux → systemd --user unit\n"
)


def _install_root() -> Path:
    from jaeger_ai.core.instance.instance import PACKAGE_ROOT
    return PACKAGE_ROOT.parent


def _jaeger_exe(home: Path) -> Path:
    """The executable autostart runs — the venv console script if present
    (the real entry point), else the install's ``./jaeger`` wrapper."""
    venv_exe = home / ".venv" / "bin" / "jaeger"
    return venv_exe if venv_exe.exists() else home / "jaeger"


def _log_path(home: Path) -> Path:
    return home / ".jaeger_os" / "autostart.log"


# ── service-file content (pure — unit-tested) ──────────────────────


def _launchd_plist(jaeger_exe: Path, home: Path, args: list[str]) -> str:
    prog = "".join(f"    <string>{a}</string>\n"
                   for a in (str(jaeger_exe), *args))
    log = _log_path(home)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
        '<plist version="1.0">\n'
        '<dict>\n'
        f'  <key>Label</key><string>{_LABEL}</string>\n'
        '  <key>ProgramArguments</key>\n'
        '  <array>\n'
        f'{prog}'
        '  </array>\n'
        '  <key>RunAtLoad</key><true/>\n'
        '  <key>KeepAlive</key><true/>\n'
        f'  <key>WorkingDirectory</key><string>{home}</string>\n'
        f'  <key>StandardOutPath</key><string>{log}</string>\n'
        f'  <key>StandardErrorPath</key><string>{log}</string>\n'
        '</dict>\n'
        '</plist>\n'
    )


def _systemd_unit(jaeger_exe: Path, home: Path, args: list[str]) -> str:
    execstart = " ".join([str(jaeger_exe), *args])
    return (
        "[Unit]\n"
        "Description=JROS (Jaeger-OS) agent\n"
        "After=network-online.target\n"
        "Wants=network-online.target\n"
        "\n"
        "[Service]\n"
        f"ExecStart={execstart}\n"
        f"WorkingDirectory={home}\n"
        "Restart=on-failure\n"
        "RestartSec=10\n"
        "\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


# ── macOS (launchd LaunchAgent) ────────────────────────────────────


def _macos_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{_LABEL}.plist"


def _macos_enable(args: list[str]) -> int:
    home = _install_root()
    plist = _macos_plist_path()
    plist.parent.mkdir(parents=True, exist_ok=True)
    _log_path(home).parent.mkdir(parents=True, exist_ok=True)
    plist.write_text(_launchd_plist(_jaeger_exe(home), home, args), encoding="utf-8")
    # Idempotent re-enable: unload a prior copy first (harmless if absent).
    subprocess.run(["launchctl", "unload", str(plist)], capture_output=True)
    # ``load -w`` is deprecated on recent macOS but still works everywhere;
    # bootstrap/bootout would tie us to a UID + newer launchctl.
    res = subprocess.run(["launchctl", "load", "-w", str(plist)],
                         capture_output=True, text=True)
    if res.returncode != 0:
        print(f"[autostart] launchctl load failed: {res.stderr.strip()}",
              file=sys.stderr)
        return 1
    print(f"[autostart] enabled — {plist}")
    print(f"[autostart] logs → {_log_path(home)}")
    print("[autostart] starts at next login; `jaeger autostart disable` to remove.")
    return 0


def _macos_disable() -> int:
    plist = _macos_plist_path()
    if not plist.exists():
        print("[autostart] not enabled (no LaunchAgent).")
        return 0
    subprocess.run(["launchctl", "unload", "-w", str(plist)], capture_output=True)
    plist.unlink()
    print(f"[autostart] disabled — removed {plist}")
    return 0


def _macos_status() -> int:
    plist = _macos_plist_path()
    if not plist.exists():
        print("[autostart] disabled (no LaunchAgent).")
        return 1
    loaded = subprocess.run(["launchctl", "list", _LABEL], capture_output=True)
    state = "loaded" if loaded.returncode == 0 else "installed, not loaded"
    print(f"[autostart] enabled — {plist} ({state})")
    return 0


# ── Linux (systemd --user) ─────────────────────────────────────────


def _linux_unit_path() -> Path:
    return Path.home() / ".config" / "systemd" / "user" / _UNIT


def _systemctl(*a: str) -> subprocess.CompletedProcess:
    return subprocess.run(["systemctl", "--user", *a],
                          capture_output=True, text=True)


def _linux_enable(args: list[str]) -> int:
    home = _install_root()
    unit = _linux_unit_path()
    unit.parent.mkdir(parents=True, exist_ok=True)
    unit.write_text(_systemd_unit(_jaeger_exe(home), home, args), encoding="utf-8")
    _systemctl("daemon-reload")
    res = _systemctl("enable", "--now", _UNIT)
    if res.returncode != 0:
        print(f"[autostart] systemctl enable failed: {res.stderr.strip()}",
              file=sys.stderr)
        return 1
    # Linger → the unit comes up at boot even with no interactive login.
    user = os.environ.get("USER", "")
    if subprocess.run(["loginctl", "enable-linger", user],
                      capture_output=True).returncode != 0:
        print(f"[autostart] note: for boot-without-login run "
              f"`sudo loginctl enable-linger {user}`.")
    print(f"[autostart] enabled — {unit}")
    print("[autostart] `jaeger autostart disable` to remove.")
    return 0


def _linux_disable() -> int:
    unit = _linux_unit_path()
    if not unit.exists():
        print("[autostart] not enabled (no systemd unit).")
        return 0
    _systemctl("disable", "--now", _UNIT)
    unit.unlink()
    _systemctl("daemon-reload")
    print(f"[autostart] disabled — removed {unit}")
    return 0


def _linux_status() -> int:
    unit = _linux_unit_path()
    if not unit.exists():
        print("[autostart] disabled (no systemd unit).")
        return 1
    active = _systemctl("is-active", _UNIT).stdout.strip() or "inactive"
    print(f"[autostart] enabled — {unit} ({active})")
    return 0


# ── dispatch ───────────────────────────────────────────────────────


def _cmd_autostart_argv(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(_USAGE, file=sys.stderr)
        return 0 if argv else 2
    action, extra = argv[0], argv[1:]
    if action not in ("enable", "disable", "status"):
        print(f"[autostart] unknown action: {action!r}", file=sys.stderr)
        print(_USAGE, file=sys.stderr)
        return 2

    if sys.platform == "darwin":
        table = {"enable": lambda: _macos_enable(extra),
                 "disable": _macos_disable, "status": _macos_status}
    elif sys.platform.startswith("linux"):
        table = {"enable": lambda: _linux_enable(extra),
                 "disable": _linux_disable, "status": _linux_status}
    else:
        print(f"[autostart] unsupported platform: {sys.platform} "
              "(macOS + Linux only).", file=sys.stderr)
        return 2
    return table[action]()


__all__ = ["_cmd_autostart_argv"]
