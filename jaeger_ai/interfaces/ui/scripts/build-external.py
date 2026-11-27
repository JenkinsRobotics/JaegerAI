"""Build and optionally test the modular @jaeger/ui-* WebUI outside the repository."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test", action="store_true", help="run component tests before building")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path.home() / ".cache/jaeger/ui-rebuild-mainscreen",
    )
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1]
    repo = source.parents[2]
    cache = args.output_root.expanduser().resolve()
    if cache == repo or repo in cache.parents:
        parser.error("output-root must be outside the repository")
    cache.mkdir(parents=True, exist_ok=True)
    snapshot = Path(tempfile.mkdtemp(prefix="build-", dir=cache))
    work = snapshot / "jaeger_ai" / "interfaces" / "ui"

    for pkg_name in ("jaeger-ui-protocol", "jaeger-ui-sdk", "jaeger-ui-kit", "jaeger-ui-avatar", "jaeger-ui-office", "jaeger-ui-features"):
        pkg_src = repo / "packages" / pkg_name
        if pkg_src.is_dir():
            shutil.copytree(
                pkg_src,
                snapshot / "packages" / pkg_name,
                dirs_exist_ok=True,
                ignore=shutil.ignore_patterns("node_modules", "dist", ".git"),
            )
    shutil.copytree(
        source,
        work,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("node_modules", "dist", ".git", "test-results", "playwright-report"),
    )

    dependencies = os.environ.get("JAEGER_UI_DEPENDENCIES")
    if dependencies:
        dep_path = Path(dependencies).expanduser().resolve()
        (work / "node_modules").symlink_to(dep_path / "node_modules", target_is_directory=True)
    else:
        subprocess.run(["npm", "ci"], cwd=work, check=True)

    env = dict(os.environ)
    if args.test:
        subprocess.run(["npm", "test", "--", "--no-cache"], cwd=work, env=env, check=True)
    subprocess.run(["npm", "run", "build"], cwd=work, env=env, check=True)
    if not (work / "dist/index.html").is_file():
        raise RuntimeError("UI build produced no index.html")

    output = cache / "dist"
    if output.exists():
        previous = cache / "previous" / (time.strftime("%Y%m%d-%H%M%S") + "-" + str(os.getpid()))
        previous.mkdir(parents=True)
        shutil.move(str(output), str(previous / output.name))
    shutil.move(str(work / "dist"), str(output))
    print("Canonical modular UI built:", output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
