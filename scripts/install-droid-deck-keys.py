#!/usr/bin/env python3
"""Install modular Gateway Droid control applets and bind Stream Deck keys."""
import argparse
import copy
import json
import os
import plistlib
import shlex
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path


OLD = "com.jenkinsrobotics.droid.toggle"
WAKE_BUNDLE_IDS = (OLD, "com.jenkinsrobotics.droid.droid", "com.jenkinsrobotics.droid.wake")
STREAM_DECK_APP = "Elgato Stream Deck"
STREAM_DECK_PROC = "Stream Deck"
PARK_PAN_ARCSEC = 0
PARK_TILT_ARCSEC = -306000
ALL_ACTIONS = ("wake", "sleep", "droid", "stop", "look", "mute")
APPLET_META = {
    "wake": ("com.jenkinsrobotics.droid.wake", "Wake Droid"),
    "sleep": ("com.jenkinsrobotics.droid.sleep", "Go to Sleep"),
    "droid": ("com.jenkinsrobotics.droid.droid", "Droid Toggle"),
    "stop": ("com.jenkinsrobotics.droid.stop", "Stop Droid"),
    "look": ("com.jenkinsrobotics.droid.look", "Look Around"),
    "mute": ("com.jenkinsrobotics.droid.mute", "Mute Droid"),
}


def binding(template, app, action, *, new=False):
    key = copy.deepcopy(template)
    title = "WAKE\nDROID" if action == "wake" else "GO TO\nSLEEP"
    if new:
        key["ActionID"] = str(uuid.uuid4())
    key["Settings"].update(
        app_name=title.replace("\n", " "),
        bundle_id=f"com.jenkinsrobotics.droid.{action}",
        bundle_path=str(app),
        source=str(app),
        exec=str(app / "Contents/MacOS/runner"),
    )
    key["States"][0].update(Title=title, ShowTitle=True)
    return key


def codesign_applet(app: Path) -> bool:
    """Best-effort ad-hoc codesign so LaunchServices/Stream Deck launches cleanly."""
    codesign = Path("/usr/bin/codesign")
    if not codesign.is_file():
        return False
    try:
        res = subprocess.run(
            [str(codesign), "--force", "--sign", "-", str(app)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10.0,
            check=False,
        )
        return res.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def _header(root: Path) -> str:
    log_dir = shlex.quote(str(root / "logs"))
    log = shlex.quote(str(root / "logs/droid-controls.log"))
    return (
        "#!/bin/sh\n"
        "set -eu\n"
        f"mkdir -p {log_dir}\n"
        f"exec >>{log} 2>&1\n"
        "ts() { /bin/date '+%Y-%m-%dT%H:%M:%S%z'; }\n"
    )


def _estop_gate(resources_url: str, action_label: str) -> str:
    return (
        f"if ! res=$(/usr/bin/curl -fsS --max-time 3 {resources_url} 2>&1); then\n"
        f'  echo "$(ts) Droid {action_label} blocked: Gateway resources unreachable ($res)"\n'
        "  exit 1\n"
        "fi\n"
        'if ! state=$(printf \'%s\' "$res" | /usr/bin/plutil -extract resources.estop_active raw -o - - 2>/dev/null); then\n'
        f'  echo "$(ts) Droid {action_label} blocked: Gateway E-Stop state unreadable"\n'
        "  exit 1\n"
        "fi\n"
        'if [ "$state" != "false" ]; then\n'
        f'  echo "$(ts) Droid {action_label} blocked: Gateway E-Stop is active or unknown ($state)"\n'
        "  exit 1\n"
        "fi\n"
    )


def _sleep_park_script(root: Path, gateway: str, *, label: str, reason: str) -> str:
    gw = gateway.rstrip("/")
    sleep_url = shlex.quote(f"{gw}/v1/droid/sleep")
    ptz = shlex.quote(str(root / "droid/bin/droid-ptz"))
    payload = shlex.quote(json.dumps({"reason": reason}, separators=(",", ":")))
    return (
        _header(root)
        + f"# Fail-safe privacy action ({label}): NEVER block sleep/camera-park on E-Stop!\n"
        "parked=0\n"
        f"if resp=$(/usr/bin/curl -fsS --max-time 10 -X POST -H 'Content-Type: application/json' -d {payload} {sleep_url} 2>&1); then\n"
        f'  echo "$(ts) Droid {label} ok via Gateway: $resp"\n'
        "  parked=1\n"
        "else\n"
        f'  echo "$(ts) Droid {label} Gateway call failed ($resp); falling back to droid-ptz"\n'
        f"  if [ -x {ptz} ]; then\n"
        f"    if ptz_out=$({ptz} abs {PARK_PAN_ARCSEC} {PARK_TILT_ARCSEC} 2>&1); then\n"
        f'      echo "$(ts) Droid {label} fallback droid-ptz ok: $ptz_out"\n'
        "      parked=1\n"
        "    else\n"
        f'      echo "$(ts) Droid {label} fallback droid-ptz failed: $ptz_out"\n'
        "    fi\n"
        "  else\n"
        f'    echo "$(ts) Droid {label} fallback droid-ptz not executable at {ptz}"\n'
        "  fi\n"
        "fi\n"
        '[ "$parked" -eq 1 ]\n'
    )


def _build_runner_script(root: Path, action: str, gateway: str) -> str:
    gw = gateway.rstrip("/")
    resources = shlex.quote(f"{gw}/v1/system/resources")
    wake_url = shlex.quote(f"{gw}/v1/droid/wake")
    status_url = shlex.quote(f"{gw}/v1/droid/status")
    act_url = shlex.quote(f"{gw}/v1/embodiment/droid/act")

    if action == "wake":
        return (
            _header(root)
            + _estop_gate(resources, "wake")
            + f"if ! resp=$(/usr/bin/curl -fsS --max-time 15 -X POST -H 'Content-Type: application/json' -d '{{\"reason\":\"stream_deck\"}}' {wake_url} 2>&1); then\n"
            '  echo "$(ts) Droid wake failed via Gateway: $resp"\n'
            "  exit 1\n"
            "fi\n"
            'echo "$(ts) Droid wake ok: $resp"\n'
        )

    if action == "sleep":
        return _sleep_park_script(root, gateway, label="sleep", reason="stream_deck")

    if action == "stop":
        return _sleep_park_script(root, gateway, label="stop", reason="stream_deck_stop")

    if action == "droid":
        sleep_runner = shlex.quote(str(root / "droid/controls/Jaeger-sleep.app/Contents/MacOS/runner"))
        wake_runner = shlex.quote(str(root / "droid/controls/Jaeger-wake.app/Contents/MacOS/runner"))
        return (
            _header(root)
            + "# Legacy toggle bundle: sleep is fail-safe even under E-Stop; wake stays E-Stop gated.\n"
            + f"if ! status_json=$(/usr/bin/curl -fsS --max-time 3 {status_url} 2>&1); then\n"
            '  echo "$(ts) Droid toggle aborted: Gateway droid status unreachable ($status_json)"\n'
            "  exit 1\n"
            "fi\n"
            'if ! sleeping=$(printf \'%s\' "$status_json" | /usr/bin/plutil -extract sleeping raw -o - - 2>/dev/null); then\n'
            '  echo "$(ts) Droid toggle aborted: Gateway droid sleeping state unreadable"\n'
            "  exit 1\n"
            "fi\n"
            'if [ "$sleeping" = "false" ]; then\n'
            '  echo "$(ts) Droid toggle: awake -> invoking Jaeger-sleep.app"\n'
            f"  if [ ! -x {sleep_runner} ]; then\n"
            f'    echo "$(ts) Droid toggle failed: sleep runner not executable at {sleep_runner}"\n'
            "    exit 1\n"
            "  fi\n"
            f"  exec {sleep_runner}\n"
            'elif [ "$sleeping" = "true" ]; then\n'
            '  echo "$(ts) Droid toggle: asleep -> invoking Jaeger-wake.app"\n'
            f"  if [ ! -x {wake_runner} ]; then\n"
            f'    echo "$(ts) Droid toggle failed: wake runner not executable at {wake_runner}"\n'
            "    exit 1\n"
            "  fi\n"
            f"  exec {wake_runner}\n"
            "else\n"
            '  echo "$(ts) Droid toggle aborted: unexpected sleeping state ($sleeping)"\n'
            "  exit 1\n"
            "fi\n"
        )

    if action == "look":
        return (
            _header(root)
            + _estop_gate(resources, "look")
            + f"if ! status_json=$(/usr/bin/curl -fsS --max-time 3 {status_url} 2>&1); then\n"
            '  echo "$(ts) Droid look failed: Gateway droid status unreachable ($status_json)"\n'
            "  exit 1\n"
            "fi\n"
            'if ! sleeping=$(printf \'%s\' "$status_json" | /usr/bin/plutil -extract sleeping raw -o - - 2>/dev/null); then\n'
            '  echo "$(ts) Droid look failed: Gateway droid sleeping state unreadable"\n'
            "  exit 1\n"
            "fi\n"
            'if [ "$sleeping" = "true" ]; then\n'
            f"  if ! wake_resp=$(/usr/bin/curl -fsS --max-time 15 -X POST -H 'Content-Type: application/json' -d '{{\"reason\":\"stream_deck_look\"}}' {wake_url} 2>&1); then\n"
            '    echo "$(ts) Droid look failed to wake Droid: $wake_resp"\n'
            "    exit 1\n"
            "  fi\n"
            '  echo "$(ts) Droid look woke sleeping Droid: $wake_resp"\n'
            "fi\n"
            'pause="${JAEGER_DROID_LOOK_PAUSE:-0.8}"\n'
            f"if ! resp=$(/usr/bin/curl -fsS --max-time 10 -X POST -H 'Content-Type: application/json' -d '{{\"action\":\"look_at\",\"params\":{{\"pan_deg\":-35,\"tilt_deg\":0}}}}' {act_url} 2>&1); then\n"
            '  echo "$(ts) Droid look left failed: $resp"\n'
            "  exit 1\n"
            "fi\n"
            '/bin/sleep "$pause"\n'
            f"if ! resp=$(/usr/bin/curl -fsS --max-time 10 -X POST -H 'Content-Type: application/json' -d '{{\"action\":\"look_at\",\"params\":{{\"pan_deg\":35,\"tilt_deg\":0}}}}' {act_url} 2>&1); then\n"
            '  echo "$(ts) Droid look right failed: $resp"\n'
            "  exit 1\n"
            "fi\n"
            '/bin/sleep "$pause"\n'
            f"if ! resp=$(/usr/bin/curl -fsS --max-time 10 -X POST -H 'Content-Type: application/json' -d '{{\"action\":\"center\",\"params\":{{}}}}' {act_url} 2>&1); then\n"
            '  echo "$(ts) Droid look center failed: $resp"\n'
            "  exit 1\n"
            "fi\n"
            'echo "$(ts) Droid look sweep ok: $resp"\n'
        )

    if action == "mute":
        return (
            _header(root)
            + 'echo "$(ts) Droid mute pressed: use Jaeger WebUI / voice orb mic control (legacy control.sock retired)"\n'
            "exit 0\n"
        )

    raise ValueError(f"Unsupported droid deck action: {action}")


def applet(root, action, gateway, *, sign=True):
    root = Path(root)
    if action not in APPLET_META:
        raise ValueError(f"Unsupported droid deck action: {action}")
    bundle_id, bundle_name = APPLET_META[action]
    app = root / "droid/controls" / f"Jaeger-{action}.app"
    runner = app / "Contents/MacOS/runner"
    runner.parent.mkdir(parents=True, exist_ok=True)
    (app / "Contents/Info.plist").write_bytes(plistlib.dumps({
        "CFBundleIdentifier": bundle_id,
        "CFBundleName": bundle_name,
        "CFBundleExecutable": "runner",
        "CFBundlePackageType": "APPL",
        "LSUIElement": True,
    }))
    script = _build_runner_script(root, action, gateway)
    runner.write_text(script, encoding="utf-8")
    runner.chmod(0o755)
    if sign:
        codesign_applet(app)
    return app


def install_applets(root, gateway, *, sign=True):
    """Generate and ad-hoc codesign all 6 Droid control .app bundles."""
    root = Path(root)
    return {action: applet(root, action, gateway, sign=sign) for action in ALL_ACTIONS}


def stream_deck_running():
    try:
        res = subprocess.run(
            ["/usr/bin/pgrep", "-x", STREAM_DECK_PROC],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return res.returncode == 0
    except OSError:
        return False


def quit_stream_deck(timeout=5.0):
    if not stream_deck_running():
        return False
    subprocess.run(
        ["/usr/bin/osascript", "-e", f'tell application "{STREAM_DECK_APP}" to quit'],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        timeout=5.0,
    )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not stream_deck_running():
            return True
        time.sleep(0.2)
    raise SystemExit(
        f"{STREAM_DECK_APP} did not exit within {timeout:.1f}s; aborting manifest update to avoid overwrite"
    )


def relaunch_stream_deck():
    subprocess.run(
        ["/usr/bin/open", "-g", "-a", STREAM_DECK_APP],
        check=True,
        timeout=10.0,
    )


def load_pages(page_path, wake_pages, parser):
    updates = []
    for path in [page_path, *wake_pages]:
        raw = path.read_bytes()
        page = json.loads(raw)
        actions, = [c["Actions"] for c in page["Controllers"] if c["Type"] == "Keypad"]
        slot, = [
            k for k, v in actions.items()
            if v.get("Settings", {}).get("bundle_id") in WAKE_BUNDLE_IDS
        ]
        template = actions[slot]
        if path == page_path:
            if page["Name"] != "DROID":
                parser.error("The sleep key must be added to a page named DROID")
            sleep = actions.get("4,0")
            if sleep and sleep.get("Settings", {}).get("bundle_id") != "com.jenkinsrobotics.droid.sleep":
                parser.error("Droid slot 4,0 is occupied")
        updates.append((path, raw, page, actions, slot, template))
    return updates


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, default=Path.home() / ".jaeger")
    parser.add_argument("--gateway", default="http://127.0.0.1:33418")
    parser.add_argument("--page", type=Path, default=None)
    parser.add_argument("--wake-page", type=Path, action="append", default=[])
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--applets-only",
        action="store_true",
        help="Refresh all 6 Droid control .app bundles without modifying Stream Deck manifests.",
    )
    parser.add_argument(
        "--reload-stream-deck",
        action="store_true",
        help="Quit Elgato Stream Deck before updating ProfilesV3 manifests, then relaunch it.",
    )
    args = parser.parse_args(argv)

    if args.applets_only:
        controls_dir = args.state_dir / "droid/controls"
        print(
            f"Applets ({len(ALL_ACTIONS)}): "
            + ", ".join(f"Jaeger-{action}.app" for action in ALL_ACTIONS)
            + f" -> {controls_dir}"
        )
        if not args.apply:
            return
        apps = install_applets(args.state_dir, args.gateway)
        for action in ALL_ACTIONS:
            print(f"Updated {apps[action]}")
        return

    if args.page is None:
        parser.error("--page is required unless --applets-only is specified")

    updates = load_pages(args.page, args.wake_page, parser)
    for path, _raw, _page, _actions, slot, _template in updates:
        print(f"{path.parent.name}: Wake at {slot}" + (", Sleep at 4,0" if path == args.page else ""))
    print(f"Applets ({len(ALL_ACTIONS)}): " + ", ".join(f"Jaeger-{action}.app" for action in ALL_ACTIONS))
    if not args.apply:
        return

    relaunch_needed = False
    if args.reload_stream_deck:
        relaunch_needed = quit_stream_deck(timeout=5.0)
        # Re-read manifests after Stream Deck flushes and exits so our baseline matches disk.
        updates = load_pages(args.page, args.wake_page, parser)
    elif stream_deck_running():
        print(
            f"Warning: {STREAM_DECK_APP} is running; pass --reload-stream-deck so edits are not overwritten from RAM.",
            file=sys.stderr,
        )

    try:
        droid_dir = args.state_dir / "droid"
        droid_dir.mkdir(parents=True, exist_ok=True)
        backup = Path(tempfile.mkdtemp(prefix="jaeger-deck-backup-", dir=droid_dir))
        print(f"Profile backup: {backup}", flush=True)
        for path, raw, *_ in updates:
            (backup / f"{path.parent.name}.json").write_bytes(raw)
        apps = install_applets(args.state_dir, args.gateway)
        wake = apps["wake"]
        sleep_app = apps["sleep"]
        for path, raw, page, actions, slot, template in updates:
            if path.read_bytes() != raw:
                raise SystemExit(f"Profile changed during update: {path}")
            actions[slot] = binding(template, wake, "wake")
            if path == args.page:
                existing = actions.get("4,0")
                actions["4,0"] = binding(existing or template, sleep_app, "sleep", new=existing is None)
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as tmp:
                tmp.write(json.dumps(page, ensure_ascii=False, separators=(",", ":")).encode())
                os.fchmod(tmp.fileno(), path.stat().st_mode & 0o777)
            os.replace(tmp.name, path)
    finally:
        if args.reload_stream_deck and (relaunch_needed or not stream_deck_running()):
            relaunch_stream_deck()


if __name__ == "__main__":
    main()
