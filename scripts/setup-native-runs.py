#!/usr/bin/env python3
"""Provision per-profile credentials for the approval-capable native Runs API.

Preserves all existing provider/model/session settings and profile comments.
The WebUI overlay must be deployed before restarting the native adapters.
"""
import os
import argparse
from pathlib import Path
import re
import secrets
import shutil

import yaml


def configure(home=None, profiles=("jaeger", "openclaw")):
    home = Path(home or Path.home())
    for profile in profiles:
        if profile not in {'jaeger', 'openclaw', 'roundtable'}:
            raise ValueError('Unsupported profile')
        path = home / ".hermes/profiles" / profile / "config.yaml"
        text = path.read_text()
        config = yaml.safe_load(text) or {}
        if config.get("webui_gateway_api_key"):
            continue
        backup = path.with_name("config.before-native-runs.yaml")
        if not backup.exists():
            shutil.copy2(path, backup)
            backup.chmod(0o600)
        value = secrets.token_urlsafe(32)
        line = f"webui_gateway_api_key: {value}"
        if re.search(r"^webui_gateway_api_key:.*$", text, re.M):
            text = re.sub(r"^webui_gateway_api_key:.*$", line, text, flags=re.M)
        else:
            text = text.rstrip() + "\n" + line + "\n"
        temporary = path.with_suffix(".native.tmp")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as output:
            output.write(text)
        os.replace(temporary, path)
        print(f"{profile}: native Runs API credential configured (not displayed)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profiles', nargs='+', choices=('jaeger', 'openclaw', 'roundtable'), default=['jaeger', 'openclaw'])
    configure(profiles=parser.parse_args().profiles)
