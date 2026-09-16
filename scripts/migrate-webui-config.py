#!/usr/bin/env python3
"""Remove retired Hermes WebUI container settings from Jaeger instances."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import yaml

RETIRED_KEYS = {
    "use_hermes_webui",
    "hermes_webui_container",
    "hermes_webui_port",
}


def migrate(path: Path) -> bool:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    containers = raw.get("containers")
    if not isinstance(containers, dict) or not RETIRED_KEYS.intersection(containers):
        return False
    backup = path.with_suffix(path.suffix + ".pre-webui-consolidation")
    if not backup.exists():
        backup.write_bytes(path.read_bytes())
        backup.chmod(0o600)
    for key in RETIRED_KEYS:
        containers.pop(key, None)
    temporary = path.with_suffix(path.suffix + ".webui-migration-tmp")
    temporary.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    os.replace(temporary, path)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--state-root",
        type=Path,
        default=Path(os.environ.get("JAEGER_STATE_DIR") or os.environ.get("JAEGER_HOME") or Path.home() / ".jaeger"),
    )
    args = parser.parse_args()
    changed = []
    for path in sorted((args.state_root / "instances").glob("*/config.yaml")):
        if migrate(path):
            changed.append(str(path))
    print(f"Migrated {len(changed)} Jaeger instance configuration(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
