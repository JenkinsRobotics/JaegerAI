#!/usr/bin/env python3
"""Wheel cleanliness audit — refuse to ship a wheel that carries
packager-machine runtime state.

The 0.1.0 wheel accidentally bundled the JaegerAI dev machine's
``instance/default/config.yaml`` / ``identity.yaml`` / ``manifest.json``
plus stale ``logs/audit.log`` and ``memory/episodic.jsonl``. Every
``pip install jaeger-os`` user loaded our state before their own. The
fix has two halves:

* MANIFEST.in + pyproject ``exclude-package-data`` keep the leak out of
  freshly-built artifacts (HYGIENE-1/2 in docs/ROADMAP_0.2.0.md).
* This post-build check rejects the obsolete instance tree, interpreter
  caches, native build output, model weights, environment files, and unsafe
  archive paths in every package, including JaegerAI and JaegerAgent.

Usage:
    scripts/check_wheel.py                  # newest dist/*.whl
    scripts/check_wheel.py path/to/file.whl

Exit codes:
    0 — wheel is clean
    1 — wheel ships a banned path (printed)
    2 — invocation error (no wheel found, etc.)
"""

from __future__ import annotations

import sys
import zipfile
import hashlib
from pathlib import Path, PurePosixPath

REPO = Path(__file__).resolve().parent.parent.parent


# INST-10 (0.2.0): ``jaeger_os/instance/`` no longer exists. Anything
# the wheel ships under that prefix is a regression — user state
# belongs at ``~/.jaeger/instances/<name>/``, created by the wizard
# at first run. The allow-list is intentionally empty.
ALLOWED_INSTANCE_FILES: set[str] = set()
VAD_ASSET = "jaeger_agent/assets/silero/silero_vad_16k_op15.onnx"
VAD_SHA256 = "b6875a49bacf6d57826a7e0a549d5a05d769ee34405cadcc9ff8b4442544b1f9"


def _find_default_wheel() -> Path:
    dist = REPO / "dist"
    if not dist.exists():
        sys.stderr.write(f"no dist/ directory at {dist}\n")
        sys.exit(2)
    candidates = sorted(dist.glob("*.whl"), key=lambda p: p.stat().st_mtime)
    if not candidates:
        sys.stderr.write(f"no .whl files in {dist}\n")
        sys.exit(2)
    return candidates[-1]


def check_wheel(wheel_path: Path) -> list[str]:
    """Return a list of forbidden paths the wheel ships."""
    violations: list[str] = []
    with zipfile.ZipFile(wheel_path) as zf:
        names = zf.namelist()
        if "jaeger_agent/core/assets.py" in names and VAD_ASSET not in names:
            violations.append(f"missing required asset: {VAD_ASSET}")
        if VAD_ASSET in names and hashlib.sha256(zf.read(VAD_ASSET)).hexdigest() != VAD_SHA256:
            violations.append(f"unexpected reference model checksum: {VAD_ASSET}")
    for name in names:
        if name.endswith("/"):
            continue  # directory entry — not a file
        path = PurePosixPath(name)
        state = {"__pycache__", ".git", ".build", ".venv", ".jaeger_os", ".jaeger_agent"}
        if (name.startswith("jaeger_os/instance/")
                or state.intersection(path.parts)
                or path.suffix.lower() in {".pyc", ".pyo", ".gguf", ".safetensors"}
                or (path.suffix.lower() == ".onnx" and name != VAD_ASSET)
                or path.name == ".env" or path.name.startswith(".env.")
                or ".." in path.parts or path.is_absolute()):
            violations.append(name)
    return violations


def main(argv: list[str]) -> int:
    if len(argv) > 2:
        sys.stderr.write(f"usage: {argv[0]} [wheel_path]\n")
        return 2
    wheel = Path(argv[1]).resolve() if len(argv) == 2 else _find_default_wheel()
    if not wheel.exists():
        sys.stderr.write(f"no such wheel: {wheel}\n")
        return 2
    violations = check_wheel(wheel)
    if violations:
        sys.stderr.write(f"\n[check_wheel] {wheel.name}: {len(violations)} forbidden file(s):\n")
        for v in violations:
            sys.stderr.write(f"  - {v}\n")
        sys.stderr.write(
            "\nThese files are packager-machine state and must NOT travel\n"
            "in the wheel. Correct package exclusions and rebuild.\n"
        )
        return 1
    print(f"[check_wheel] {wheel.name}: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
