#!/usr/bin/env python3
"""sync_design_tokens.py — Validates and synchronizes design tokens across platforms.

Reads the single source of truth:
  jaeger_ai/assets/design-system/aether-default.json

Verifies consistency with:
  jaeger_ai/assets/design-system/tokens.css
  jaeger_ai/interfaces/ui/scripts/check-theme-literals.mjs
"""

from __future__ import annotations

import json
from pathlib import Path
import sys
import subprocess

REPO_ROOT = Path(__file__).resolve().parents[2]
TOKEN_JSON = REPO_ROOT / "jaeger_ai" / "assets" / "design-system" / "aether-default.json"
TOKEN_CSS = REPO_ROOT / "jaeger_ai" / "assets" / "design-system" / "tokens.css"


def check_tokens() -> bool:
    if not TOKEN_JSON.is_file():
        print(f"[-] ERROR: Missing {TOKEN_JSON}")
        return False
    if not TOKEN_CSS.is_file():
        print(f"[-] ERROR: Missing {TOKEN_CSS}")
        return False
    with open(TOKEN_JSON, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Verify dark mode colors exist
    dark_modes = data.get("modes", {}).get("dark", {})
    required_colors = ["color-bg-app", "color-bg-shell", "color-border", "color-text", "color-accent"]
    for col in required_colors:
        if col not in dark_modes:
            print(f"[-] ERROR: Missing required token '{col}' in {TOKEN_JSON}")
            return False

    css_text = TOKEN_CSS.read_text(encoding="utf-8")
    for col in required_colors:
        if f"--aether-{col}" not in css_text:
            print(f"[-] ERROR: Token '--aether-{col}' not found in {TOKEN_CSS}")
            return False

    ui = REPO_ROOT / "jaeger_ai/interfaces/ui"
    result = subprocess.run(["node", "scripts/check-theme-literals.mjs"], cwd=ui, check=False)
    if result.returncode:
        return False
    print("[+] Design tokens and canonical shared UI theme rules verified.")
    return True


if __name__ == "__main__":
    success = check_tokens()
    sys.exit(0 if success else 1)

