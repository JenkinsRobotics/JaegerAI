"""``jaeger host`` — macOS appliance & hardware host management.

Manages the underlying host machine (e.g. Mac Studio) for 24/7 persistent
autonomous robot operation:
  - `jaeger host setup`     Run the automated robot host setup
  - `jaeger host status`    Inspect power, auto-restart, LaunchAgent, and memory stats
  - `jaeger host optimize`  Apply power & memory baseline optimizations
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path

_USAGE = (
    "usage: jaeger host {setup|status|optimize} [options]\n"
    "\n"
    "  setup [opts]   Configure this Mac for 24/7 persistent robot operation\n"
    "                 (dedicated 'jaeger' user, power recovery, LaunchAgent).\n"
    "  status         Display host power settings, LaunchAgent state, and memory.\n"
    "  optimize       Apply power & memory baseline optimizations (pmset, Spotlight).\n"
    "\n"
    "Options:\n"
    "  --non-interactive   Run setup without interactive prompts\n"
    "  --user <name>       Target robot username (default: jaeger)\n"
)


def _install_root() -> Path:
    from jaeger_ai.core.instance.instance import install_root
    return install_root()


def host_verb(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(_USAGE)
        return 0

    sub = argv[0]
    extra = argv[1:]

    if platform.system() != "Darwin":
        print("[host] Error: 'jaeger host' commands are currently specific to macOS.", file=sys.stderr)
        return 1

    if sub == "setup":
        script = _install_root() / "scripts" / "setup-mac-robot.sh"
        if not script.exists():
            print(f"[host] Setup script not found at {script}", file=sys.stderr)
            return 1
        cmd = ["bash", str(script), *extra]
        return subprocess.run(cmd).returncode

    if sub == "optimize":
        print("[host] Applying hardware power & energy optimizations...")
        subprocess.run(["sudo", "pmset", "-a", "autorestart", "1"], check=False)
        subprocess.run(["sudo", "pmset", "-a", "sleep", "0"], check=False)
        subprocess.run(["sudo", "pmset", "-a", "disksleep", "0"], check=False)
        subprocess.run(["sudo", "pmset", "-a", "displaysleep", "15"], check=False)
        subprocess.run(["sudo", "systemsetup", "-setrestartfreeze", "on"], check=False)
        print("[host] Power & sleep settings optimized.")

        # Exclude from Spotlight
        repo = _install_root()
        (repo / ".metadata_never_index").touch()
        state_dir = Path.home() / ".jaeger"
        if state_dir.exists():
            (state_dir / ".metadata_never_index").touch()
        print("[host] Spotlight indexing exclusions applied.")
        return 0

    if sub == "status":
        print("=== Jaeger Host Status (macOS) ===")
        # Power settings
        print("\n--- Power & Sleep Settings (pmset) ---")
        res = subprocess.run(["pmset", "-g"], capture_output=True, text=True, check=False)
        for line in res.stdout.splitlines():
            if any(k in line for k in ("autorestart", "sleep", "disksleep", "displaysleep", "womp")):
                print(" ", line.strip())

        # Check LaunchAgent
        print("\n--- LaunchAgent Status ---")
        agent_plist = Path.home() / "Library" / "LaunchAgents" / "com.jenkinsrobotics.jaeger.plist"
        if agent_plist.exists():
            loaded = subprocess.run(["launchctl", "list", "com.jenkinsrobotics.jaeger"], capture_output=True)
            state = "LOADED & ACTIVE" if loaded.returncode == 0 else "INSTALLED, NOT LOADED"
            print(f"  Service: {agent_plist} ({state})")
        else:
            print("  Service: Not installed in ~/Library/LaunchAgents")

        # Memory summary
        print("\n--- Virtual Memory Summary ---")
        vm = subprocess.run(["vm_stat"], capture_output=True, text=True, check=False)
        lines = vm.stdout.splitlines()
        for line in lines[:6]:
            print(" ", line.strip())
        return 0

    print(f"[host] Unknown subcommand: {sub}\n")
    print(_USAGE)
    return 2

