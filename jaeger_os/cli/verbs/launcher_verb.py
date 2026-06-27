"""``jaeger launcher`` — a clickable macOS ``.app`` that launches the agent.

A **thin** launcher (no bundling, no signing): ``Jaeger.app`` whose
``Contents/MacOS/Jaeger`` stub just execs the install's ``jaeger`` command.
Because it's *created locally* (not downloaded), it carries no quarantine
flag — it opens without the "unidentified developer" block, no notarization.
macOS only; the agent + its `.venv` stay exactly where the installer put them.

  jaeger launcher install   drop Jaeger.app into /Applications (Dock/Launchpad)
  jaeger launcher remove    delete it
"""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

_APP_NAME = "Jaeger.app"
_BUNDLE_ID = "com.jenkinsrobotics.jaeger"
_LSREGISTER = (
    "/System/Library/Frameworks/CoreServices.framework/Frameworks/"
    "LaunchServices.framework/Support/lsregister"
)
_USAGE = (
    "usage: jaeger launcher {install|remove}\n"
    "\n"
    "  install   create a clickable Jaeger.app (Dock / Launchpad) that runs\n"
    "            this install's `jaeger`. Thin launcher — no bundling/signing,\n"
    "            opens without a Gatekeeper prompt. Opt-in.\n"
    "  remove    delete the launcher.\n"
)


def _install_root() -> Path:
    from jaeger_os.core.instance.instance import PACKAGE_ROOT
    return PACKAGE_ROOT.parent


def _jaeger_exe(home: Path) -> Path:
    """The command the launcher execs — venv console script if present, else
    the install's ``./jaeger`` wrapper."""
    venv = home / ".venv" / "bin" / "jaeger"
    return venv if venv.exists() else home / "jaeger"


def _app_dir() -> Path:
    """``/Applications`` if writable (the discoverable spot, no sudo on a
    typical single-admin Mac), else ``~/Applications`` (always user-writable)."""
    sys_apps = Path("/Applications")
    if sys_apps.is_dir() and os.access(sys_apps, os.W_OK):
        return sys_apps / _APP_NAME
    return Path.home() / "Applications" / _APP_NAME


# ── bundle content (pure — unit-tested) ────────────────────────────


def _stub_script(jaeger_exe: Path) -> str:
    return (
        "#!/bin/bash\n"
        "# Thin launcher created locally by `jaeger launcher install` — no\n"
        "# bundling/signing. Execs the JROS agent in place.\n"
        f'exec "{jaeger_exe}" "$@"\n'
    )


def _info_plist() -> dict:
    import jaeger_os
    return {
        "CFBundleName": "Jaeger",
        "CFBundleDisplayName": "Jaeger",
        "CFBundleIdentifier": _BUNDLE_ID,
        "CFBundleExecutable": "Jaeger",
        "CFBundlePackageType": "APPL",
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleShortVersionString": jaeger_os.__version__,
        "LSMinimumSystemVersion": "11.0",
        "NSHighResolutionCapable": True,
    }


def _write_bundle(app: Path, jaeger_exe: Path) -> Path:
    """Write a minimal .app bundle at ``app`` (Contents/MacOS/Jaeger stub +
    Contents/Info.plist). Returns the stub path."""
    macos = app / "Contents" / "MacOS"
    macos.mkdir(parents=True, exist_ok=True)
    stub = macos / "Jaeger"
    stub.write_text(_stub_script(jaeger_exe), encoding="utf-8")
    stub.chmod(0o755)
    with open(app / "Contents" / "Info.plist", "wb") as f:
        plistlib.dump(_info_plist(), f)
    return stub


# ── install / remove (macOS IO) ────────────────────────────────────


def _macos_install() -> int:
    home = _install_root()
    exe = _jaeger_exe(home)
    app = _app_dir()
    if app.exists():
        shutil.rmtree(app)          # idempotent re-install
    _write_bundle(app, exe)
    # Best-effort: register with LaunchServices so it shows immediately in
    # Spotlight / Launchpad without a re-login.
    subprocess.run([_LSREGISTER, "-f", str(app)], capture_output=True)
    print(f"[launcher] installed {app}")
    print(f"[launcher] it runs: {exe}")
    print("[launcher] open it from Launchpad / Applications, or `jaeger "
          "launcher remove` to delete.")
    return 0


def _macos_remove() -> int:
    removed = []
    for a in (Path("/Applications") / _APP_NAME,
              Path.home() / "Applications" / _APP_NAME):
        if a.exists():
            shutil.rmtree(a)
            removed.append(str(a))
    if removed:
        print(f"[launcher] removed {', '.join(removed)}")
    else:
        print("[launcher] no launcher installed.")
    return 0


def _cmd_launcher_argv(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(_USAGE, file=sys.stderr)
        return 0 if argv else 2
    action = argv[0]
    if action not in ("install", "remove"):
        print(f"[launcher] unknown action: {action!r}", file=sys.stderr)
        print(_USAGE, file=sys.stderr)
        return 2
    if sys.platform != "darwin":
        print("[launcher] macOS only (the clickable .app). On Linux use "
              "`jaeger autostart` for a boot service.", file=sys.stderr)
        return 2
    return _macos_install() if action == "install" else _macos_remove()


__all__ = ["_cmd_launcher_argv"]
