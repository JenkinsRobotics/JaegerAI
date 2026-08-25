#!/usr/bin/env python3
"""Fail a release when an archive contains workstation/runtime residue."""

from __future__ import annotations

import argparse
import re
import tarfile
import zipfile
from pathlib import Path

FORBIDDEN = re.compile(
    r"(^|/)(?:__pycache__|\.pytest_cache|\.mypy_cache|\.ruff_cache|\.build|build|dist)(/|$)"
    r"|\.(?:py[co]|db|sqlite(?:3)?|log)$|(^|/)\.DS_Store$"
)


def members(path: Path) -> list[str]:
    if path.suffix == ".whl" or zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            return archive.namelist()
    if path.name.endswith((".tar.gz", ".tgz")):
        with tarfile.open(path) as archive:
            return archive.getnames()
    return []


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    artifacts = sorted(p for p in args.directory.iterdir() if p.is_file())
    if not artifacts:
        parser.error("no release artifacts found")
    failed = False
    for artifact in artifacts:
        bad = [name for name in members(artifact) if FORBIDDEN.search(name)]
        if bad:
            failed = True
            print(f"{artifact}: forbidden members")
            for name in bad:
                print(f"  {name}")
        else:
            print(f"{artifact}: clean")
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
