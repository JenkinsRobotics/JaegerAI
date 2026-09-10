#!/usr/bin/env python3
"""Copy Jaeger-patched Hermes WebUI static files into the live container.

Keeps display_name labeling (Hermes Agent vs "default") after image recreates.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = "/opt/homebrew/bin/container"
NAME = "jaeger-hermes-webui"
FILES = ("panels.js", "ui.js", "boot.js", "index.html", "sw.js")
SRC = ROOT / "vendor/hermes-webui/static"


def main() -> int:
    for name in FILES:
        src = SRC / name
        if not src.is_file():
            print(f"missing {src}", file=sys.stderr)
            return 1
        dest = f"{NAME}:/app/static/{name}"
        result = subprocess.run([ENGINE, "cp", str(src), dest], capture_output=True, text=True)
        if result.returncode:
            print(result.stderr or result.stdout or f"cp failed for {name}", file=sys.stderr)
            return result.returncode
        print(f"synced {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
