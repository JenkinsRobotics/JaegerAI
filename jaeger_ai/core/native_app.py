"""Shared location for native build artifacts, outside the source checkout."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path


def swift_build_dir(repo: Path) -> Path:
    override = os.environ.get("JAEGER_SWIFT_BUILD_DIR")
    if override:
        return Path(override).expanduser().resolve()
    checkout = hashlib.sha256(str(repo.resolve()).encode()).hexdigest()[:12]
    return Path.home() / ".cache" / "jaeger" / "swift" / checkout


def swift_app_bundle(repo: Path) -> Path:
    return swift_build_dir(repo) / "JaegerAI.app"


if __name__ == "__main__":
    import sys

    print(swift_build_dir(Path(sys.argv[1])))
