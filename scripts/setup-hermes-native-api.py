#!/usr/bin/env python3
"""Install the repo-owned native Hermes API supervisor, without changing profiles.

Dry run by default. Start only after the explicit test API process is stopped.
This service starts only Hermes' authenticated API, not its messaging platforms.
"""
import argparse
import os
from pathlib import Path
import plistlib
import runpy
import subprocess

ROOT = Path(__file__).resolve().parents[1]
LABEL = "com.jenkinsrobotics.hermes-native-api"


def configuration():
    logs = ROOT / ".jaeger_ai/shared/logs"
    return {"Label": LABEL, "ProgramArguments": [str(ROOT/".venv/bin/python"), str(ROOT/"scripts/hermes-native-api-service.py")],
            "WorkingDirectory": str(ROOT), "RunAtLoad": True, "KeepAlive": True,
            "ThrottleInterval": 20, "StandardOutPath": str(logs/(LABEL+".log")),
            "StandardErrorPath": str(logs/(LABEL+".err.log"))}


def install():
    path = Path.home()/"Library/LaunchAgents"/(LABEL+".plist")
    if path.exists():
        raise RuntimeError("Service already configured; inspect before changing or restarting it")
    module = runpy.run_path(str(ROOT/"scripts/run-hermes-native-api.py"))
    module['provision_key'](Path.home()/".hermes/jaeger-native-api.key")
    config = configuration()
    Path(config['StandardOutPath']).parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'wb') as output:
        plistlib.dump(config, output)
    subprocess.run(['/bin/launchctl', 'bootstrap', f'gui/{os.getuid()}', str(path)], check=True, timeout=15)
    print(f'Installed {LABEL}; verify readiness separately. Rollback: launchctl bootout gui/{os.getuid()}/{LABEL}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install', action='store_true')
    args = parser.parse_args()
    if args.install:
        install()
    else:
        print(plistlib.dumps(configuration()).decode())
