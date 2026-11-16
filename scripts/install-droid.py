"""Install or update Droid mode on this Mac.

Builds the Jaeger Droid host (only when its Swift source changed, so macOS
keeps its microphone and camera permissions). The host runs headless and no
longer shows a menu-bar icon; Droid controls live in the Jaeger menu. Also
registers the host to start at login, builds the small native helpers
(droid-ptz: the camera gimbal over UVC; droid-display: a virtual display when
no monitor is attached), restarts the Python droid service so it runs the
current code, and with ``--install-deck`` points the Stream Deck at Droid
mode: WAKE DROID, LOOK, STOP and MUTE keys (LOOK/STOP replace the old VIDEO
CHAT/STOP CHAT keys, whose applets are moved out, never deleted).
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import plistlib
import shlex
import shutil
import subprocess
import time
import uuid

LABEL = "com.jenkinsrobotics.jaeger-droid"
BUNDLE_ID = "com.jenkinsrobotics.jaeger.droid"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install-deck", action="store_true", help="point WAKE DROID keys at Droid mode")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    root = Path(os.environ.get("JAEGER_STATE_DIR") or Path.home() / ".jaeger")
    python = root / "voice-venv/bin/python"
    if not python.exists():
        raise SystemExit("The realtime voice venv (~/.jaeger/voice-venv) is missing")
    logs = root / "logs"
    logs.mkdir(exist_ok=True)
    config = root / "droid.json"
    if not config.exists():
        config.write_text(json.dumps({"speaker": "Mac Studio Speakers", "microphone": "Insta360 Link 2",
                                      "camera": "Insta360 Link 2",
                                      "engine": "local", "session_id": "agent-native:jaeger",
                                      "name": "Matthew"}, indent=2))
        config.chmod(0o600)

    source = repo / "jaeger_ai/features/droid/native/DroidHost.swift"
    digest = hashlib.sha256(source.read_bytes()).hexdigest()[:16]
    host = root / "droid/Jaeger Droid.app"
    info_path = host / "Contents/Info.plist"
    info = {"CFBundleIdentifier": BUNDLE_ID, "CFBundleName": "Jaeger Droid", "CFBundleDisplayName": "Jaeger Droid",
            "CFBundleExecutable": "DroidHost", "CFBundlePackageType": "APPL", "CFBundleShortVersionString": "1.0",
            "LSUIElement": True, "JaegerPython": str(python), "JaegerSource": str(repo), "JaegerHostHash": digest,
            "NSMicrophoneUsageDescription": "Jaeger listens through this Mac's microphone while Droid mode is awake.",
            "NSCameraUsageDescription": "Jaeger looks through the camera in Droid mode; frames stay on this Mac."}
    current = plistlib.loads(info_path.read_bytes()) if info_path.exists() else {}
    rebuilt = current != info
    if rebuilt:
        binary = host / "Contents/MacOS/DroidHost"
        binary.parent.mkdir(parents=True, exist_ok=True)
        built = binary.with_suffix(".new")
        subprocess.run(["xcrun", "swiftc", "-O", str(source), "-o", str(built),
                        "-framework", "AppKit", "-framework", "AVFoundation"], check=True)
        built.replace(binary)
        with info_path.open("wb") as handle:
            plistlib.dump(info, handle)
        subprocess.run(["codesign", "--force", "--sign", "-", "--identifier", BUNDLE_ID, str(host)], check=True)

    build_helpers(repo, root)

    agents = Path.home() / "Library/LaunchAgents"
    plist = agents / f"{LABEL}.plist"
    job = {"Label": LABEL, "ProgramArguments": ["/usr/bin/open", "-W", "-g", "-a", str(host)],
           "WorkingDirectory": str(repo), "RunAtLoad": True, "KeepAlive": True, "ThrottleInterval": 10,
           "EnvironmentVariables": {"JAEGER_STATE_DIR": str(root), "HF_HUB_OFFLINE": "1",
                                    "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"},
           "StandardOutPath": str(logs / "droid.log"), "StandardErrorPath": str(logs / "droid.log")}
    domain = f"gui/{os.getuid()}"
    service = f"{domain}/{LABEL}"
    loaded = subprocess.run(["launchctl", "print", service], capture_output=True).returncode == 0
    old = plistlib.loads(plist.read_bytes()) if plist.exists() else None
    if rebuilt or old != job or not loaded:
        if loaded:
            subprocess.run(["launchctl", "bootout", service], capture_output=True)
            subprocess.run(["osascript", "-e", 'if application id "%s" is running then tell application id "%s" to quit' % (BUNDLE_ID, BUNDLE_ID)], capture_output=True)
            time.sleep(1.5)
        agents.mkdir(parents=True, exist_ok=True)
        with plist.open("wb") as handle:
            plistlib.dump(job, handle)
        subprocess.run(["launchctl", "bootstrap", domain, str(plist)], check=True)
        print("Jaeger Droid host", "rebuilt and started" if rebuilt else "started")
    else:
        # Same host: restart only the Python service; the host relaunches it in ~3 s.
        subprocess.run(["pkill", "-TERM", "-f", "jaeger_ai.features.droid.service"], capture_output=True)
        print("Droid service restarted on current code")

    if args.install_deck:
        install_deck(root, logs)


def build_helpers(repo: Path, root: Path):
    """Compile the Objective-C helpers when their source changed (no permissions involved)."""
    native = repo / "jaeger_ai/features/droid/native"
    bin_dir = root / "droid/bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    for name, frameworks in (("droid-ptz", ["IOKit", "Foundation"]),
                             ("droid-display", ["Foundation", "CoreGraphics"])):
        source = native / f"{name}.m"
        target = bin_dir / name
        stamp = bin_dir / f".{name}.sha"
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        if target.exists() and stamp.exists() and stamp.read_text() == digest:
            continue
        flags = [arg for fw in frameworks for arg in ("-framework", fw)]
        subprocess.run(["xcrun", "clang", "-fobjc-arc", "-O2", str(source), "-o", str(target.with_suffix(".new")), *flags],
                       check=True)
        target.with_suffix(".new").replace(target)
        stamp.write_text(digest)
        print("built", name)


# Stream Deck keys for Droid mode: title on the key -> (applet name, action, JSON body).
KEYS = {"WAKE DROID": ("droid", "toggle", None), "LOOK": ("look", "look", '{"around":true}'),
        "STOP": ("stop", "stop", None), "MUTE": ("mute", "mute", None)}
# Old conversation keys that Droid mode replaces, and the key that takes each slot.
REPLACES = {"VIDEO CHAT": "LOOK", "STOP CHAT": "STOP"}
OLD_APPLETS = ("Jaeger-video.app", "Jaeger-off.app")


def make_applet(root: Path, logs: Path, name: str, action: str, body: str | None) -> Path:
    applet = root / f"droid/controls/Jaeger-{name}.app"
    runner = applet / "Contents/MacOS/runner"
    runner.parent.mkdir(parents=True, exist_ok=True)
    with (applet / "Contents/Info.plist").open("wb") as handle:
        plistlib.dump({"CFBundleIdentifier": f"com.jenkinsrobotics.droid.{name}", "CFBundleName": name.upper(),
                       "CFBundleExecutable": "runner", "CFBundlePackageType": "APPL", "LSUIElement": True}, handle)
    sock = shlex.quote(str(root / "run/droid/control.sock"))
    data = f" -H 'Content-Type: application/json' -d {shlex.quote(body)}" if body else ""
    wake = action == "toggle"
    runner.write_text(f"""#!/bin/sh
# Stream Deck: Droid mode {action} (Jaeger's droid service on its unix socket).
for i in {'1 2 3 4 5 6 7 8 9 10 11 12 13 14 15' if wake else '1 2'}; do
  /usr/bin/curl -s -m 5 --unix-socket {sock} -X POST{data} http://droid/{action} >/dev/null && exit 0
  {'[ "$i" = 1 ] && /bin/launchctl kickstart gui/$(id -u)/' + LABEL if wake else ':'}
  sleep 1
done
echo "$(date) droid {action}: service unreachable" >> {shlex.quote(str(logs / 'droid-controls.log'))}
""")
    runner.chmod(0o755)
    return applet


def install_deck(root: Path, logs: Path):
    applets = {title: make_applet(root, logs, *spec) for title, spec in KEYS.items()}

    def point(act: dict, title: str) -> bool:
        applet = applets[title]
        settings = act.setdefault("Settings", {})
        label = title.replace(" ", "\n")
        if settings.get("bundle_path") == str(applet) and act["States"][0].get("Title") == label:
            return False
        settings.update({"app_name": title, "bundle_id": f"com.jenkinsrobotics.droid.{KEYS[title][0]}",
                         "bundle_path": str(applet), "exec": str(applet / "Contents/MacOS/runner"),
                         "source": str(applet), "is_bundle": True, "bring_to_front": False, "args": "",
                         "long_press": "none"})
        act["States"][0]["Title"] = label
        act["States"][0].pop("Image", None)
        return True

    deck = Path.home() / "Library/Application Support/com.elgato.StreamDeck/ProfilesV3"
    changed = []
    for manifest in deck.glob("*.sdProfile/Profiles/*/manifest.json"):
        data = json.loads(manifest.read_text())
        dirty = False
        for controller in data.get("Controllers") or []:
            actions = controller.get("Actions") or {}
            stop_slot = None
            for key, act in actions.items():
                if act.get("UUID") != "com.elgato.streamdeck.system.openapp" or not act.get("States"):
                    continue
                title = (act["States"][0].get("Title") or "").replace("\n", " ").strip().upper()
                title = REPLACES.get(title, title)
                if title in KEYS:
                    dirty |= point(act, title)
                    if title == "STOP":
                        stop_slot = key
            # MUTE sits right after STOP when that slot is free.
            if stop_slot and not any(((a.get("States") or [{}])[0].get("Title") or "").replace("\n", " ").upper() == "MUTE"
                                     for a in actions.values()):
                col, row = (int(v) for v in stop_slot.split(","))
                slot = f"{col + 1},{row}"
                if slot not in actions and col + 1 <= 4:
                    mute = copy.deepcopy(actions[stop_slot])
                    mute["ActionID"] = str(uuid.uuid4())
                    point(mute, "MUTE")
                    actions[slot] = mute
                    dirty = True
        if dirty:
            changed.append((manifest, data))
    move_old_applets(root)
    if not changed:
        print("Stream Deck already points at Droid mode")
        return
    backup = root / "backups" / f"stream-deck-droid-{time.time_ns()}"
    backup.mkdir(parents=True, exist_ok=True)
    for manifest, _ in changed:
        shutil.copy2(manifest, backup / (manifest.parent.name + ".json"))
    subprocess.run(["osascript", "-e", 'tell application id "com.elgato.StreamDeck" to quit'], capture_output=True)
    time.sleep(2.5)
    for manifest, data in changed:
        manifest.write_text(json.dumps(data))
    subprocess.run(["open", "-g", "-b", "com.elgato.StreamDeck"], check=False)
    print(f"Stream Deck: {len(changed)} page(s) now drive Droid mode (backup in {backup})")


def move_old_applets(root: Path):
    """The old VIDEO CHAT / STOP CHAT applets move to the removed-items folder (never deleted)."""
    removed = Path.home() / "Desktop/Jaeger-removed-2026-11-15/conversation-controls"
    for name in OLD_APPLETS:
        old = root / "conversation-controls" / name
        if old.exists():
            removed.mkdir(parents=True, exist_ok=True)
            target = removed / name
            if target.exists():
                target = removed / f"{old.stem}-{time.time_ns()}.app"
            shutil.move(str(old), str(target))
            print("moved", old, "->", target)


if __name__ == "__main__":
    main()
