#!/usr/bin/env python3
"""Materialize pinned upstream plus Jaeger-owned patches without editing donor repos."""
from pathlib import Path
import io
import shutil
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def prepare():
    donor = ROOT / "vendor/hermes-webui"
    overlay = ROOT / "integrations/hermes_webui"
    destination = Path(tempfile.mkdtemp(prefix="jaeger-webui-"))
    archive = subprocess.check_output(["git", "-C", str(donor), "archive", "HEAD"])
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        tar.extractall(destination, filter="data")
    subprocess.run(["git", "apply", "--check", str(overlay / "upstream.patch")], cwd=destination, check=True)
    subprocess.run(["git", "apply", str(overlay / "upstream.patch")], cwd=destination, check=True)
    shutil.copy2(overlay / "jaeger_ollama.py", destination / "api/jaeger_ollama.py")
    shutil.copy2(overlay / "jaeger_agent_compat.py", destination / "api/jaeger_agent_compat.py")
    shutil.copy2(overlay / "jaeger_gateway_routes.py", destination / "api/jaeger_gateway_routes.py")
    # Package explicitly: some Apple Container builders drop nested context
    # updates during incremental directory COPY. The build validates contents.
    with tarfile.open(destination / "jaeger-overlay.tar.gz", "w:gz") as tar:
        for name in ("api", "static", "docker_init.bash"):
            tar.add(destination / name, arcname=name)
    shutil.copy2(overlay / "Containerfile", destination / "Containerfile.jaeger")
    print(destination)
    return destination


if __name__ == "__main__":
    prepare()
