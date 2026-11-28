"""Install an extracted Jaeger Core bundle on macOS, Linux or Windows."""

from __future__ import annotations

import argparse
import subprocess
import sys
import venv
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--venv", type=Path, default=Path.home() / ".jaeger" / "core-venv")
    args = parser.parse_args()
    if not (3, 11) <= sys.version_info[:2] < (3, 13):
        parser.error("Jaeger Core requires Python 3.11 or 3.12.")
    wheels = sorted((Path(__file__).resolve().parent / "wheelhouse").glob("*.whl"))
    if not any(p.name.startswith("jaeger_ai-") for p in wheels):
        parser.error("Extract the complete Jaeger Core release archive first.")

    target = args.venv.expanduser().resolve()
    python = target / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    if not python.is_file():
        venv.EnvBuilder(with_pip=True, symlinks=sys.platform != "win32").create(target)
    # Pass all bundled first-party wheels explicitly so pip does not fetch
    # same-named packages from an index. Third-party dependencies use pip.
    subprocess.run([str(python), "-m", "pip", "install", *(str(p) for p in wheels)], check=True)
    subprocess.run([str(python), "-m", "pip", "check"], check=True)
    invoke = "& " if sys.platform == "win32" else ""
    print(f'Run: {invoke}"{python}" -m jaeger_ai core')
    print("Open: http://127.0.0.1:8790")


if __name__ == "__main__":
    main()
