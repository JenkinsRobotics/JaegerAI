"""Build the browser-first portable release without modifying a checkout."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

REPO = Path(__file__).resolve().parents[1]
SOURCE_PATHS = ("pyproject.toml", "README.md", "LICENSE", "MANIFEST.in", "jaeger_ai", "packages")
PRIVATE_NAMES = {
    "credentials.json", "identity.json", "entity_identity.json", "remote_hosts.json",
    "memory.md", "user.md", "secrets.env", "id_ed25519", "id_rsa",
}


def stage_tracked_sources(repo: Path, stage: Path) -> None:
    """Do not read untracked files, app state, or a developer's cached WebUI."""
    repo = repo.resolve()
    tracked = subprocess.check_output(["git", "ls-files", "-z", "--", *SOURCE_PATHS], cwd=repo)
    for name in tracked.split(b"\0"):
        if not name:
            continue
        rel = Path(os.fsdecode(name))
        src = repo / rel
        private = (
            rel.name.lower() in PRIVATE_NAMES
            or rel.name.lower() == ".env" or rel.name.lower().startswith(".env.")
            or any(part.startswith(".jaeger") for part in rel.parts)
            or rel.suffix.lower() in {".sqlite", ".sqlite3", ".db", ".pem", ".p12", ".pfx", ".key"}
        )
        if private:
            raise ValueError(f"Personal state or credentials must not be packaged: {rel}")
        if src.is_symlink() or not src.resolve().is_relative_to(repo) or not src.is_file():
            raise ValueError(f"Expected an ordinary tracked source file: {rel}")
        dest = stage / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)


def build(output: Path) -> Path:
    with tempfile.TemporaryDirectory(prefix="jaeger-core-build-") as temp:
        scratch = Path(temp)
        stage = scratch / "source"
        stage_tracked_sources(REPO, stage)
        subprocess.run([
            sys.executable, "-B", str(stage / "jaeger_ai/interfaces/ui/scripts/build-external.py"),
            "--output-root", str(scratch / "ui"),
        ], check=True)
        ui_dist = scratch / "ui/dist"
        if not (ui_dist / "index.html").is_file() or not any((ui_dist / "assets").glob("*.js")):
            raise ValueError("A built WebUI with index.html and JavaScript assets is required.")

        shutil.copytree(ui_dist, stage / "jaeger_ai/assets/shared-ui")

        # The portable distribution includes the pure-Python Gateway modules,
        # not the native Kokoro/Whisper engines or the macOS application.
        projects = [stage]
        for src in sorted((stage / "packages").glob("*/src")):
            if (src.parent / "pyproject.toml").is_file():
                projects.append(src.parent)
        wheels = scratch / "wheelhouse"
        subprocess.run([
            sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation",
            "--wheel-dir", str(wheels), *(str(p) for p in projects),
        ], check=True)

        artifacts = sorted(wheels.glob("*.whl"))
        root_wheel, = wheels.glob("jaeger_ai-*.whl")
        if len(artifacts) != len(projects) or any(not p.name.endswith("-none-any.whl") for p in artifacts):
            raise RuntimeError("Expected one platform-independent wheel per Core project.")
        with ZipFile(root_wheel) as wheel:
            paths = wheel.namelist()
            prefix = "jaeger_ai/assets/shared-ui/"
            if prefix + "index.html" not in paths or not any(
                f.startswith(prefix + "assets/") and f.endswith(".js") for f in paths
            ):
                raise RuntimeError("Core wheel is missing its WebUI.")

        version = re.fullmatch(r"jaeger_ai-(.+)-py3-none-any\.whl", root_wheel.name)
        if version is None:
            raise RuntimeError(f"Unexpected root wheel: {root_wheel.name}")
        output.mkdir(parents=True, exist_ok=True)
        bundle = output / f"jaeger-core-{version[1]}.zip"
        with ZipFile(bundle, "w", compression=ZIP_DEFLATED, compresslevel=6) as archive:
            archive.write(REPO / "scripts/install-core.py", "install-core.py")
            for wheel in artifacts:
                archive.write(wheel, f"wheelhouse/{wheel.name}")
        return bundle


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", required=True, type=Path)
    args = ap.parse_args()
    print(build(args.output.resolve()))


if __name__ == "__main__":
    main()
