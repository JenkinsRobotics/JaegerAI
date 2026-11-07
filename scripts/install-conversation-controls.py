"""Install local conversation controls and two keys on an existing Jaeger deck page."""
from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import plistlib
import shlex
import shutil
import subprocess
import sys
import time
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-device", required=True)
    parser.add_argument("--output-device", required=True)
    parser.add_argument("--camera-index", type=int, default=0)
    parser.add_argument("--vision-model-path", required=True)
    parser.add_argument("--install-deck", action="store_true")
    parser.add_argument("--visual-context", choices=["local", "cloud"], help="Keep visual answers local or share text descriptions with the Gateway model")
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(repo))
    from jaeger_ai.core.instance.instance import operator_state_root

    root = operator_state_root()
    logs = root / "logs"
    logs.mkdir(exist_ok=True)
    model = Path(args.vision_model_path).expanduser().resolve()
    if not model.is_dir():
        raise SystemExit("Local vision model directory does not exist")
    config = root / "conversation.json"
    settings = json.loads(config.read_text()) if config.exists() else {}
    if config.exists():
        shutil.copy2(config, config.with_suffix(f".backup-{time.time_ns()}.json"))
    settings.update(input_device=args.input_device, output_device=args.output_device,
                    camera_index=args.camera_index, vision_model_path=str(model))
    if args.visual_context is not None:
        settings["share_visual_context"] = args.visual_context == "cloud"
    settings.setdefault("share_visual_context", False)
    config.write_text(json.dumps(settings, indent=2))
    config.chmod(0o600)
    label = "com.jenkinsrobotics.jaeger.conversation"
    agents = Path.home() / "Library/LaunchAgents"
    agents.mkdir(parents=True, exist_ok=True)
    plist = agents / f"{label}.plist"
    domain = f"gui/{os.getuid()}"
    service = f"{domain}/{label}"
    subprocess.run(["launchctl", "bootout", service], capture_output=True)
    deadline = time.monotonic() + 10
    while subprocess.run(["launchctl", "print", service], capture_output=True).returncode == 0:
        if time.monotonic() >= deadline:
            raise SystemExit("Previous conversation service did not unload")
        time.sleep(0.2)
    environment = {"PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1",
                   "PYTHONPATH": os.pathsep.join(str(repo / path) for path in
                       (".", "packages/jaeger-os", "packages/jaeger-agent",
                        "packages/jaeger-whisper-stt", "packages/jaeger-kokoro-tts")),
                   "JAEGER_STATE_DIR": str(root), "HF_HUB_OFFLINE": "1",
                   "TOKENIZERS_PARALLELISM": "false", "PYTORCH_ENABLE_MPS_FALLBACK": "1",
                   "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"}
    host = root / "conversation-controls/Jaeger Conversation.app"
    binary = host / "Contents/MacOS/ConversationHost"
    if host.exists():
        subprocess.run(["osascript", "-e", 'if application "Jaeger Conversation" is running then tell application "Jaeger Conversation" to quit'], capture_output=True)
    binary.parent.mkdir(parents=True, exist_ok=True)
    with (host / "Contents/Info.plist").open("wb") as output:
        plistlib.dump({"CFBundleIdentifier": label, "CFBundleName": "Jaeger Conversation",
                      "CFBundleExecutable": "ConversationHost", "CFBundlePackageType": "APPL",
                      "LSUIElement": True, "JaegerPython": sys.executable, "JaegerSource": str(repo),
                      "NSMicrophoneUsageDescription": "Jaeger listens while Voice Mode or Video Chat is enabled.",
                      "NSCameraUsageDescription": "Jaeger processes camera frames locally while Video Chat is enabled."}, output)
    subprocess.run(["xcrun", "swiftc", str(repo / "jaeger_ai/features/voice/native/ConversationHost.swift"),
                    "-o", str(binary), "-framework", "AppKit", "-framework", "AVFoundation"], check=True)
    subprocess.run(["codesign", "--force", "--sign", "-", str(host)], check=True)
    with plist.open("wb") as output:
        plistlib.dump({"Label": label, "ProgramArguments": ["/usr/bin/open", "-W", "-g", str(host)],
                      "WorkingDirectory": str(repo), "EnvironmentVariables": environment,
                      "RunAtLoad": True, "KeepAlive": True, "ThrottleInterval": 10,
                      "StandardOutPath": str(logs / "conversation-control.log"),
                      "StandardErrorPath": str(logs / "conversation-control.log")}, output)
    subprocess.run(["launchctl", "bootstrap", domain, str(plist)], check=True)

    if args.install_deck:
        deck = Path.home() / "Library/Application Support/com.elgato.StreamDeck/ProfilesV3"
        matches = []
        for manifest in deck.glob("*.sdProfile/Profiles/*/manifest.json"):
            data = json.loads(manifest.read_text())
            if data.get("Name") == "JAEGER":
                matches.append((manifest, data))
        if len(matches) != 1:
            raise SystemExit("Expected one existing JAEGER Stream Deck page; controls installed, deck unchanged")
        manifest, data = matches[0]
        keypad = next(item for item in data["Controllers"] if item["Type"] == "Keypad")
        actions = keypad["Actions"]
        for key in ("1,1", "2,1"):
            if key in actions and actions[key].get("Settings", {}).get("bundle_id", "").startswith("com.jenkinsrobotics.conversation.") is False:
                raise SystemExit(f"Stream Deck key {key} is occupied; existing actions preserved")
        template = copy.deepcopy(actions["1,0"])
        applets = root / "conversation-controls"
        applets.mkdir(exist_ok=True)
        for mode, key, title in (("voice", "1,0", "VOICE MODE"), ("video", "1,1", "VIDEO CHAT"), ("off", "2,1", "STOP CHAT")):
            bundle = applets / f"Jaeger-{mode}.app"
            executable = bundle / "Contents/MacOS/runner"
            executable.parent.mkdir(parents=True, exist_ok=True)
            bundle_id = f"com.jenkinsrobotics.conversation.{mode}"
            with (bundle / "Contents/Info.plist").open("wb") as output:
                plistlib.dump({"CFBundleIdentifier": bundle_id, "CFBundleName": title,
                              "CFBundleExecutable": "runner", "CFBundlePackageType": "APPL", "LSUIElement": True}, output)
            command = shlex.join([sys.executable, "-B", "-m", "jaeger_ai.features.voice.control", mode])
            executable.write_text("#!/bin/sh\ncd " + shlex.quote(str(repo)) + " || exit 1\n" +
                                  "export PYTHONDONTWRITEBYTECODE=1\nexport JAEGER_STATE_DIR=" + shlex.quote(str(root)) + "\n" +
                                  command + " >> " + shlex.quote(str(logs / "conversation-controls.log")) + " 2>&1\n")
            executable.chmod(0o755)
            action = copy.deepcopy(template)
            action["ActionID"] = str(uuid.uuid4())
            action["States"] = [{"Title": title, "Icon": "Images/icon-voice.png"}]
            action["Settings"] = {"app_name": title, "bundle_id": bundle_id, "bundle_path": str(bundle),
                                  "exec": str(executable), "source": str(bundle), "is_bundle": True,
                                  "bring_to_front": False, "args": "", "long_press": "none"}
            actions[key] = action
        backup = root / "backups" / f"stream-deck-{time.time_ns()}.json"
        backup.parent.mkdir(exist_ok=True)
        shutil.copy2(manifest, backup)
        subprocess.run(["osascript", "-e", 'tell application id "com.elgato.StreamDeck" to quit'], check=True)
        time.sleep(2)
        manifest.write_text(json.dumps(data, indent=2))
        subprocess.run(["open", "-b", "com.elgato.StreamDeck"], check=True)
    print("Conversation controls installed. Microphone and camera remain off until a mode key is pressed.")


if __name__ == "__main__":
    main()
