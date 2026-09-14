"""``jaeger launcher`` — install the native, branded macOS application.

The app bundle owns the Dock identity; the agent and its virtualenv remain in
the installation directory. Local builds use ad-hoc signing, not notarization.
The thin-bundle builder remains for compatibility with older installer callers.

  jaeger launcher install   drop Jaeger AI.app into /Applications (Dock/Launchpad)
  jaeger launcher remove    delete it
"""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

_APP_NAME = "Jaeger AI.app"
_LEGACY_APP_NAMES = ("Jaeger.app",)
_BUNDLE_ID = "com.jenkinsrobotics.JaegerAI"
_LSREGISTER = (
    "/System/Library/Frameworks/CoreServices.framework/Frameworks/"
    "LaunchServices.framework/Support/lsregister"
)
_USAGE = (
    "usage: jaeger launcher {install|remove}\n"
    "\n"
    "  install   build and install the native Jaeger AI.app (Dock / Launchpad)\n"
    "            using this install's agent and the canonical desktop icon.\n"
    "            Existing Jaeger AI launchers are backed up.\n"
    "  remove    delete the launcher.\n"
)


def _install_root() -> Path:
    from jaeger_ai.core.instance.instance import PACKAGE_ROOT
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
        "# bundling/signing. Execs the JaegerAI agent in place.\n"
        f'exec "{jaeger_exe}" "$@"\n'
    )


def _info_plist() -> dict:
    import jaeger_ai
    return {
        "CFBundleName": "Jaeger AI",
        "CFBundleDisplayName": "Jaeger AI",
        "CFBundleIdentifier": _BUNDLE_ID,
        "CFBundleExecutable": "Jaeger AI",
        "CFBundlePackageType": "APPL",
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleShortVersionString": jaeger_ai.__version__,
        "LSMinimumSystemVersion": "11.0",
        "NSHighResolutionCapable": True,
    }


def _write_bundle(
    app: Path,
    jaeger_exe: Path,
    *,
    icon_source: Path | None = None,
) -> Path:
    """Write a minimal .app bundle at ``app`` (Contents/MacOS stub +
    Contents/Info.plist). Returns the stub path."""
    macos = app / "Contents" / "MacOS"
    macos.mkdir(parents=True, exist_ok=True)
    stub = macos / "Jaeger AI"
    stub.write_text(_stub_script(jaeger_exe), encoding="utf-8")
    stub.chmod(0o755)
    plist = _info_plist()
    if icon_source is not None and icon_source.is_file():
        resources = app / "Contents" / "Resources"
        resources.mkdir(parents=True, exist_ok=True)
        shutil.copy2(icon_source, resources / "AppIcon.icns")
        plist["CFBundleIconFile"] = "AppIcon"
        plist["CFBundleIconName"] = "AppIcon"
    with open(app / "Contents" / "Info.plist", "wb") as f:
        plistlib.dump(plist, f)
    return stub


# ── install / remove (macOS IO) ────────────────────────────────────


def _install_native_bundle(source: Path, app: Path, backup_root: Path) -> Path | None:
    """Replace only this product's launcher, with rollback and a saved copy."""
    for candidate in (source, app):
        if candidate == app and not candidate.exists():
            continue
        with (candidate / "Contents/Info.plist").open("rb") as stream:
            if plistlib.load(stream).get("CFBundleIdentifier") != _BUNDLE_ID:
                raise ValueError(f"Refusing to replace an unrelated app: {candidate}")
    if not (source / "Contents/Resources/AppIcon.icns").is_file():
        raise ValueError("Native app is missing the desktop icon; rebuild it first")
    app.parent.mkdir(parents=True, exist_ok=True)
    backup = None
    with tempfile.TemporaryDirectory(prefix=".jaeger-launcher-", dir=app.parent) as stage:
        staged = Path(stage) / _APP_NAME
        shutil.copytree(source, staged, symlinks=True)
        if app.exists():
            backup = backup_root / uuid.uuid4().hex / _APP_NAME
            backup.parent.mkdir(parents=True, exist_ok=True)
            app.rename(backup)
        try:
            staged.rename(app)
        except OSError:
            if backup is not None:
                backup.rename(app)
            raise
    return backup


def _macos_install() -> int:
    home = _install_root()
    app = _app_dir()
    swift = home / "jaeger_ai/interfaces/swift"
    try:
        subprocess.run(["bash", str(swift / "Scripts/build-app.sh"), "--dev"], check=True)
        source = swift / ".build/JaegerOS.app"
        subprocess.run([str(source / "Contents/MacOS/JaegerOS"), "--verify-launch"], check=True)
        from jaeger_ai.core.instance.instance import operator_state_root
        backup = _install_native_bundle(source, app, operator_state_root() / "launcher-backups")
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"[launcher] install failed: {exc}", file=sys.stderr)
        return 1
    # Best-effort: register with LaunchServices so it shows immediately in
    # Spotlight / Launchpad without a re-login.
    subprocess.run([_LSREGISTER, "-f", str(app)], capture_output=True, check=False)
    print(f"[launcher] installed {app}")
    print(f"[launcher] agent launcher: {home / 'jaeger'}")
    if backup is not None:
        print(f"[launcher] previous launcher saved: {backup}")
    print("[launcher] open it from Launchpad / Applications, or `jaeger "
          "launcher remove` to delete.")
    return 0


def _macos_remove() -> int:
    removed = []
    names = (_APP_NAME, *_LEGACY_APP_NAMES)
    for directory in (Path("/Applications"), Path.home() / "Applications"):
        for name in names:
            a = directory / name
            if not a.exists():
                continue
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
